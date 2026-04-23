"""压缩包解压主循环 (D4 / D5 / D6 决策)。

设计要点:
- 入口 ``trigger_extract`` 用 ``asyncio.create_task`` 起后台任务(D6),协程
  内自己开 session,不复用请求级 session,避免请求关闭后 DB 句柄失效
- ``INFRA_DISABLE_EXTRACT=1`` 时 ``trigger_extract`` 是 no-op,L2 测试在 fixture
  里手动 ``await extract_archive(...)``,避免协程并发干扰断言
- 顶层 try/except 总把异常落到 DB(``parse_status=failed`` + ``parse_error``),
  绝不让协程死在无人收尸的状态(Risks 表第一行)
- 重 IO 工作(zipfile/py7zr/rarfile)用 ``asyncio.to_thread`` 卸到线程池,不
  阻塞 event loop;DB 写仍走 async session
- 加密包检测(D5)不在上传时做;只在解压时遇到三种典型异常 → 标 needs_password

支持类型(D7 白名单):
- 解压并保留:.docx / .xlsx / .jpg / .png / .bmp / .tiff
- 写 bid_documents 但标 skipped(占位记录,user 可见):.doc / .xls / .pdf / 其他
- 嵌套压缩包:.zip / .7z / .rar 在 depth ≤3 时递归;超过标 skipped
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import zipfile
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.services.extract.encoding import _looks_like_utf8, decode_filename
from app.services.extract.junk_filter import is_junk_entry
from app.services.extract.safety import (
    check_count_budget,
    check_nesting_depth,
    check_safe_entry,
    check_size_budget,
)

logger = logging.getLogger(__name__)

# 可解压并保留物理文件的类型(D7)
EXTRACTABLE_FILE_EXTENSIONS = frozenset(
    {".docx", ".xlsx", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
)
# 嵌套压缩包,递归解压
NESTED_ARCHIVE_EXTENSIONS = frozenset({".zip", ".7z", ".rar"})

# 测试钩子:置 1 时 trigger_extract no-op,L2 用 fixture 手动 await
def _is_extract_disabled() -> bool:
    return os.environ.get("INFRA_DISABLE_EXTRACT") == "1"


# ----------------------------------------------------------------- 协程 entry

async def trigger_extract(
    bidder_id: int,
    password: str | None = None,
) -> asyncio.Task[None] | None:
    """非阻塞触发后台解压。

    Returns:
        ``asyncio.Task`` 句柄(测试可 ``await`` 等待)或 None(已 disable)。
    """
    if _is_extract_disabled():
        logger.info("INFRA_DISABLE_EXTRACT=1, skip auto-extract for bidder=%s", bidder_id)
        return None
    # 关键:不复用请求级 session,extract_archive 内部自开
    return asyncio.create_task(extract_archive(bidder_id, password=password))


# ----------------------------------------------------------- 核心 extract_archive

# 三种典型加密异常 → 统一映射 needs_password
class _PasswordRequiredError(Exception):
    """内部信号:抓到加密包,engine 用此异常跳出循环。"""


async def extract_archive(
    bidder_id: int,
    password: str | None = None,
    session_factory: Callable[[], Any] = async_session,
) -> None:
    """对 bidder 下所有 ``pending`` / ``needs_password`` 状态的归档行做解压。

    如调用方提供 password,只对 ``needs_password`` 行用此密码重试;否则只处理
    ``pending`` 行。

    完成后聚合所有归档行的 status 写到 ``bidders.parse_status``:
    - 全部 extracted → extracted
    - 任何 needs_password → needs_password
    - 任何 failed 且无 extracted → failed
    - 混合(部分 extracted + 部分 failed/skipped)→ partial

    C6 起外层用 ``async with track()`` 包裹,scanner 在启动期可扫到心跳
    过期的 stuck 解压任务并回滚 bidder.parse_status。
    """
    # 延迟导入避免循环依赖;测试中允许 tracker 失败不影响主流程
    from app.services.async_tasks.tracker import track

    try:
        async with track(
            subtype="extract",
            entity_type="bidder",
            entity_id=bidder_id,
        ):
            async with session_factory() as session:  # type: ignore[misc]
                try:
                    await _process_bidder(session, bidder_id, password)
                except Exception as exc:  # noqa: BLE001 - 顶层兜底
                    logger.exception(
                        "extract_archive top-level failure for bidder=%s", bidder_id
                    )
                    try:
                        await _set_bidder_failed(session, bidder_id, str(exc)[:500])
                        await session.commit()
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "failed to write bidder failed-status for %s", bidder_id
                        )
    except Exception:  # noqa: BLE001 - 上面已吞所有业务异常,这里兜底 tracker 异常
        logger.exception("extract_archive tracker failure for bidder=%s", bidder_id)


async def _process_bidder(
    session: AsyncSession, bidder_id: int, password: str | None
) -> None:
    bidder = (
        await session.execute(select(Bidder).where(Bidder.id == bidder_id))
    ).scalar_one_or_none()
    if bidder is None or bidder.deleted_at is not None:
        logger.warning("bidder %s missing or soft-deleted, skip extract", bidder_id)
        return

    # 选取需要本次处理的归档行
    target_status = "needs_password" if password else "pending"
    archive_rows = (
        await session.execute(
            select(BidDocument).where(
                BidDocument.bidder_id == bidder_id,
                BidDocument.parse_status == target_status,
                BidDocument.file_type.in_(NESTED_ARCHIVE_EXTENSIONS),
            )
        )
    ).scalars().all()
    if not archive_rows:
        logger.info("no archives to extract for bidder=%s status=%s", bidder_id, target_status)
        return

    # 整体置 extracting
    bidder.parse_status = "extracting"
    bidder.parse_error = None
    await session.commit()

    # DEF-001: 首次解压时将项目状态从 draft → parsing
    from app.services.parser.pipeline.project_status_sync import (
        try_transition_project_parsing,
    )

    await try_transition_project_parsing(bidder.project_id)

    extract_root_base = Path(settings.extracted_dir) / str(bidder.project_id) / str(bidder_id)
    extract_root_base.mkdir(parents=True, exist_ok=True)

    for archive_row in archive_rows:
        archive_row.parse_status = "extracting"
    await session.commit()

    for archive_row in archive_rows:
        await _process_one_archive(
            session=session,
            bidder=bidder,
            archive_row=archive_row,
            extract_root_base=extract_root_base,
            password=password,
        )

    # 聚合 bidder.parse_status
    await _aggregate_bidder_status(session, bidder_id)
    await session.commit()

    # C5: 解压成功进 extracted/partial 时触发 pipeline(内容提取 + LLM 分类 + 报价)
    await session.refresh(bidder)
    if bidder.parse_status in ("extracted", "partial"):
        from app.services.parser.pipeline.trigger import trigger_pipeline

        await trigger_pipeline(bidder_id)


async def _process_one_archive(
    *,
    session: AsyncSession,
    bidder: Bidder,
    archive_row: BidDocument,
    extract_root_base: Path,
    password: str | None,
) -> None:
    """处理单个归档:解压 → 写 child rows → 标归档 status。失败兜底到 failed。"""
    archive_path = Path(archive_row.file_path)
    if not archive_path.is_absolute():
        # 历史相对路径(老 storage 实现)→ 解释为相对 cwd
        archive_path = archive_path.resolve()
    if not archive_path.exists():
        archive_row.parse_status = "failed"
        archive_row.parse_error = "原始压缩包文件已不存在"
        await session.commit()
        return

    archive_extract_root = extract_root_base / archive_row.md5[:16]
    # 重新解压前清掉旧产物(密码重试场景)
    if archive_extract_root.exists():
        shutil.rmtree(archive_extract_root, ignore_errors=True)
    archive_extract_root.mkdir(parents=True, exist_ok=True)

    counters = {"bytes": 0, "count": 0}
    extracted_children: list[BidDocument] = []

    try:
        await asyncio.to_thread(
            _sync_extract,
            archive_path=archive_path,
            archive_ext=archive_row.file_type,
            extract_root=archive_extract_root,
            password=password,
            depth=1,
            counters=counters,
            on_child=lambda child: extracted_children.append(child),
            bidder_id=bidder.id,
            source_archive_name=archive_row.file_name,
        )
    except _PasswordRequiredError as exc:
        archive_row.parse_status = "needs_password"
        archive_row.parse_error = str(exc) or "需要密码"
        await session.commit()
        return
    except _ArchiveFatalError as exc:
        archive_row.parse_status = "failed"
        archive_row.parse_error = str(exc)[:500]
        await session.commit()
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("unexpected error extracting %s", archive_path)
        archive_row.parse_status = "failed"
        archive_row.parse_error = f"解压失败:{exc!s}"[:500]
        await session.commit()
        return

    # 写 child rows;UNIQUE(bidder_id, md5) 冲突 → 按文件级去重(D8 内 bidder)
    accepted = 0
    for child in extracted_children:
        # 同 bidder 内同 MD5 已存在 → 跳过本条插入,但删掉刚落盘的物理文件
        # (避免 extracted/ 残留)
        existing = (
            await session.execute(
                select(BidDocument.id).where(
                    BidDocument.bidder_id == bidder.id,
                    BidDocument.md5 == child.md5,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            try:
                Path(child.file_path).unlink(missing_ok=True)
            except OSError:
                pass
            continue
        session.add(child)
        accepted += 1

    archive_row.parse_status = _archive_final_status(extracted_children)
    if archive_row.parse_status == "failed":
        archive_row.parse_error = (
            extracted_children[-1].parse_error if extracted_children else "压缩包内无有效文件"
        )
    elif archive_row.parse_status == "extracted":
        archive_row.parse_error = None

    # 过滤统计审计留痕(fix-mac-packed-zip-parsing D5)
    junk_n = int(counters.get("junk_skipped", 0))
    if junk_n > 0:
        note = f"(已过滤 {junk_n} 个打包垃圾文件)"
        archive_row.parse_error = (
            f"{archive_row.parse_error} {note}"
            if archive_row.parse_error
            else note
        )[:500]

    bidder.file_count = (bidder.file_count or 0) + accepted
    await session.commit()


def _archive_final_status(children: list[BidDocument]) -> str:
    """根据子文件 status 列表算归档行最终状态。"""
    if not children:
        return "failed"  # 空压缩包(spec scenario)
    has_extracted = any(c.parse_status == "extracted" for c in children)
    has_skipped = any(c.parse_status == "skipped" for c in children)
    if has_extracted and not has_skipped:
        return "extracted"
    if has_extracted and has_skipped:
        return "partial"
    # 全部 skipped → 仍标 extracted(归档行成功开盒,内容不支持是另一回事)
    return "extracted"


async def _aggregate_bidder_status(session: AsyncSession, bidder_id: int) -> None:
    """按"任一规则"聚合 bidder.parse_status。"""
    rows = (
        await session.execute(
            select(BidDocument.parse_status).where(
                BidDocument.bidder_id == bidder_id,
                BidDocument.file_type.in_(NESTED_ARCHIVE_EXTENSIONS),
            )
        )
    ).scalars().all()
    bidder = (
        await session.execute(select(Bidder).where(Bidder.id == bidder_id))
    ).scalar_one()

    if not rows:
        return
    if any(r == "needs_password" for r in rows):
        bidder.parse_status = "needs_password"
    elif any(r == "extracting" for r in rows):
        bidder.parse_status = "extracting"
    elif all(r in {"extracted", "partial"} for r in rows):
        bidder.parse_status = (
            "partial" if any(r == "partial" for r in rows) else "extracted"
        )
    elif any(r == "extracted" or r == "partial" for r in rows):
        bidder.parse_status = "partial"
    else:
        bidder.parse_status = "failed"
    bidder.updated_at = datetime.now(timezone.utc)


async def _set_bidder_failed(
    session: AsyncSession, bidder_id: int, parse_error: str
) -> None:
    bidder = (
        await session.execute(select(Bidder).where(Bidder.id == bidder_id))
    ).scalar_one_or_none()
    if bidder is None:
        return
    bidder.parse_status = "failed"
    bidder.parse_error = parse_error[:500]


# ============================================================ 同步解压实现

class _ArchiveFatalError(Exception):
    """整包失败:损坏 / 不可打开 / 内部抛 OS 级异常 etc."""


def _sync_extract(
    *,
    archive_path: Path,
    archive_ext: str,
    extract_root: Path,
    password: str | None,
    depth: int,
    counters: dict[str, int],
    on_child: Callable[[BidDocument], None],
    bidder_id: int,
    source_archive_name: str,
) -> None:
    """同步解压(供 ``asyncio.to_thread`` 调用)。

    所有 IO 均同步;通过 callback ``on_child`` 反馈 ``BidDocument`` 雏形,由
    async 调用方插入 DB。预算(总字节/条目数)用 dict 跨递归共享。

    抛 ``_PasswordRequiredError`` / ``_ArchiveFatalError`` 给上层。
    """
    ext = archive_ext.lower()
    if ext == ".zip":
        _extract_zip(
            archive_path=archive_path,
            extract_root=extract_root,
            password=password,
            depth=depth,
            counters=counters,
            on_child=on_child,
            bidder_id=bidder_id,
            source_archive_name=source_archive_name,
        )
    elif ext == ".7z":
        _extract_7z(
            archive_path=archive_path,
            extract_root=extract_root,
            password=password,
            depth=depth,
            counters=counters,
            on_child=on_child,
            bidder_id=bidder_id,
            source_archive_name=source_archive_name,
        )
    elif ext == ".rar":
        _extract_rar(
            archive_path=archive_path,
            extract_root=extract_root,
            password=password,
            depth=depth,
            counters=counters,
            on_child=on_child,
            bidder_id=bidder_id,
            source_archive_name=source_archive_name,
        )
    else:
        raise _ArchiveFatalError(f"不支持的压缩格式:{ext}")


def _extract_zip(
    *,
    archive_path: Path,
    extract_root: Path,
    password: str | None,
    depth: int,
    counters: dict[str, int],
    on_child: Callable[[BidDocument], None],
    bidder_id: int,
    source_archive_name: str,
) -> None:
    try:
        zf = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise _ArchiveFatalError("文件已损坏,无法解压") from exc

    with zf:
        names = zf.namelist()
        if not names:
            raise _ArchiveFatalError("压缩包内无有效文件")

        for info in zf.infolist():
            counters["count"] += 1
            ok, reason = check_count_budget(counters["count"])
            if not ok:
                raise _ArchiveFatalError(reason)

            # 文件名编码探测:Python zipfile 在写非 ASCII 时会把 0x800 bit 置位,
            # 然后 cp437 编码字节落盘;读回时如果 0x800 设置但 UTF-8 解码失败,zipfile
            # 用 cp437 解码,得到一串 box-drawing 字符(并非真正的 UTF-8 文件名)。
            # 我们的策略:总是 try ``encode("cp437") → GBK decode`` 的回路,如果
            # decode 出全 ASCII / 中文,认为这是 GBK lying-flag 场景;否则相信
            # info.filename(genuine unicode UTF-8 entry)。
            decoded = info.filename
            warn = None
            try:
                cp437_bytes = info.filename.encode("cp437")
                # 优先:若原字节是合法 UTF-8(macOS Archive Utility 无 flag 场景)
                # 则直接用 UTF-8 解码。GBK 字节极难满足 UTF-8 字节模式规则,
                # 所以这个分支对 Windows GBK 包零影响(fix-mac-packed-zip-parsing D3)
                if _looks_like_utf8(cp437_bytes):
                    try:
                        decoded = cp437_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        # _looks_like_utf8 通过但 decode 失败,理论不会发生 → 退回启发式
                        decoded = None  # type: ignore[assignment]
                    else:
                        # 成功解出 UTF-8,跳过 GBK 启发式
                        cp437_bytes = None  # type: ignore[assignment]
                if cp437_bytes is not None:
                    # 原 GBK 启发式:cp437 字节 → GBK 解码 → 检查落点
                    gbk_view = cp437_bytes.decode("gbk")
                    if any("\u4e00" <= c <= "\u9fff" for c in gbk_view) or all(
                        32 <= ord(c) <= 126 for c in gbk_view
                    ):
                        decoded = gbk_view
                    else:
                        # GBK decode 出的也是噪声 → 走通用 decode_filename 兜底
                        decoded, warn = decode_filename(
                            cp437_bytes, is_utf8_flagged=False
                        )
            except (UnicodeEncodeError, UnicodeDecodeError):
                # info.filename 含真 unicode 字符(>0xFF),不能 cp437 编 → 信原值
                pass
            if not decoded or decoded.endswith("/"):
                # 目录 entry,跳过(下层文件 entry 自带相对路径会建目录)
                continue

            # 打包垃圾(macOS __MACOSX/._x / .DS_Store / Office ~$x / VCS / 编辑器残留):
            # 静默丢弃,不写盘也不产生 bid_documents 行(fix-mac-packed-zip-parsing D5)
            if is_junk_entry(decoded):
                counters["junk_skipped"] = counters.get("junk_skipped", 0) + 1
                continue

            # 路径安全
            ok, reason = check_safe_entry(decoded, extract_root)
            if not ok:
                _emit_skipped_child(
                    on_child=on_child,
                    bidder_id=bidder_id,
                    file_name=Path(decoded).name,
                    relative_path=decoded,
                    reason=reason,
                    source_archive=source_archive_name,
                    file_size=info.file_size,
                )
                continue

            target_path = (extract_root / decoded).resolve()
            target_path.parent.mkdir(parents=True, exist_ok=True)

            ext = Path(decoded).suffix.lower()
            # 嵌套压缩包:检查深度后递归
            if ext in NESTED_ARCHIVE_EXTENSIONS:
                ok, reason = check_nesting_depth(depth + 1)
                if not ok:
                    _emit_skipped_child(
                        on_child=on_child,
                        bidder_id=bidder_id,
                        file_name=Path(decoded).name,
                        relative_path=decoded,
                        reason=reason,
                        source_archive=source_archive_name,
                        file_size=info.file_size,
                    )
                    continue

            # 写盘并算 MD5(限大小)
            try:
                with zf.open(info, pwd=password.encode("utf-8") if password else None) as src, target_path.open("wb") as dst:
                    md5 = hashlib.md5(usedforsecurity=False)
                    written = 0
                    while True:
                        chunk = src.read(64 * 1024)
                        if not chunk:
                            break
                        md5.update(chunk)
                        dst.write(chunk)
                        written += len(chunk)
                        counters["bytes"] += len(chunk)
                        ok, reason = check_size_budget(counters["bytes"])
                        if not ok:
                            raise _ArchiveFatalError(reason)
            except RuntimeError as exc:
                # zipfile 加密失败抛 RuntimeError("Bad password" / "encrypted, password required")
                msg = str(exc).lower()
                if "password" in msg or "encrypted" in msg:
                    raise _PasswordRequiredError(
                        "密码错误" if password else "需要密码"
                    ) from exc
                raise _ArchiveFatalError(f"解压失败:{exc!s}") from exc

            if ext in NESTED_ARCHIVE_EXTENSIONS:
                # 递归;失败按子包标 skipped(不影响外层 partial 判定)
                try:
                    _sync_extract(
                        archive_path=target_path,
                        archive_ext=ext,
                        extract_root=target_path.parent / target_path.stem,
                        password=password,
                        depth=depth + 1,
                        counters=counters,
                        on_child=on_child,
                        bidder_id=bidder_id,
                        source_archive_name=source_archive_name,
                    )
                except _PasswordRequiredError:
                    _emit_skipped_child(
                        on_child=on_child,
                        bidder_id=bidder_id,
                        file_name=Path(decoded).name,
                        relative_path=decoded,
                        reason="嵌套压缩包需要密码,已跳过",
                        source_archive=source_archive_name,
                        file_size=written,
                    )
                except _ArchiveFatalError as exc:
                    _emit_skipped_child(
                        on_child=on_child,
                        bidder_id=bidder_id,
                        file_name=Path(decoded).name,
                        relative_path=decoded,
                        reason=str(exc)[:200],
                        source_archive=source_archive_name,
                        file_size=written,
                    )
                continue

            # 普通文件落地
            md5_hex = md5.hexdigest()
            if ext in EXTRACTABLE_FILE_EXTENSIONS:
                child = BidDocument(
                    bidder_id=bidder_id,
                    file_name=Path(decoded).name,
                    file_path=str(target_path),
                    file_size=written,
                    file_type=ext,
                    md5=md5_hex,
                    parse_status="extracted",
                    parse_error=warn,
                    source_archive=source_archive_name,
                )
            else:
                # 不支持:删除物理文件(只留 DB 记录占位提示用户)
                try:
                    target_path.unlink(missing_ok=True)
                except OSError:
                    pass
                child = BidDocument(
                    bidder_id=bidder_id,
                    file_name=Path(decoded).name,
                    file_path=str(target_path),
                    file_size=written,
                    file_type=ext or ".unknown",
                    md5=md5_hex,
                    parse_status="skipped",
                    parse_error=f"暂不支持 {ext} 格式",
                    source_archive=source_archive_name,
                )
            on_child(child)


def _extract_7z(
    *,
    archive_path: Path,
    extract_root: Path,
    password: str | None,
    depth: int,
    counters: dict[str, int],
    on_child: Callable[[BidDocument], None],
    bidder_id: int,
    source_archive_name: str,
) -> None:
    try:
        import py7zr
        from py7zr.exceptions import PasswordRequired
    except ImportError as exc:
        raise _ArchiveFatalError("py7zr 未安装,无法解压 7z") from exc

    # 第一步:无密码探测加密 / 损坏。py7zr 对加密包打 PasswordRequired,
    # 损坏包打其它异常(如 BadFormat)。这给我们一个干净的"是否加密"信号,
    # 后续带密码 extract 失败时就可断定是密码错而非压缩包损坏。
    is_encrypted = False
    try:
        with py7zr.SevenZipFile(archive_path, password=None) as probe:
            is_encrypted = bool(probe.needs_password())
            if not is_encrypted and probe.getnames() == []:
                raise _ArchiveFatalError("压缩包内无有效文件")
    except PasswordRequired:
        is_encrypted = True
    except _ArchiveFatalError:
        raise
    except Exception as exc:  # noqa: BLE001
        # 探测就挂 → 视为损坏
        raise _ArchiveFatalError(f"7z 解压失败:{exc!s}") from exc

    if is_encrypted and not password:
        raise _PasswordRequiredError("需要密码")

    # 第二步:带密码(或无密码非加密)正式 extract
    try:
        with py7zr.SevenZipFile(archive_path, password=password) as sz:
            sz.extractall(path=extract_root)
    except PasswordRequired as exc:
        raise _PasswordRequiredError("密码错误") from exc
    except _ArchiveFatalError:
        raise
    except Exception as exc:  # noqa: BLE001
        # 加密包带了密码却失败 → 必然是密码错;不加密的失败才是损坏
        if is_encrypted:
            raise _PasswordRequiredError("密码错误") from exc
        raise _ArchiveFatalError(f"7z 解压失败:{exc!s}") from exc

    # 7z 解压后扫盘建 child rows + 路径安全检查
    _walk_extracted_dir(
        extract_root=extract_root,
        depth=depth,
        counters=counters,
        on_child=on_child,
        bidder_id=bidder_id,
        source_archive_name=source_archive_name,
        password=password,
    )


def _extract_rar(
    *,
    archive_path: Path,
    extract_root: Path,
    password: str | None,
    depth: int,
    counters: dict[str, int],
    on_child: Callable[[BidDocument], None],
    bidder_id: int,
    source_archive_name: str,
) -> None:
    try:
        import rarfile
    except ImportError as exc:
        raise _ArchiveFatalError("rarfile 未安装,无法解压 rar") from exc

    try:
        rf = rarfile.RarFile(archive_path)
    except rarfile.BadRarFile as exc:
        raise _ArchiveFatalError("文件已损坏,无法解压") from exc
    except rarfile.NotRarFile as exc:
        raise _ArchiveFatalError("非 RAR 格式") from exc

    with rf:
        names = rf.namelist()
        if not names:
            raise _ArchiveFatalError("压缩包内无有效文件")
        try:
            if password:
                rf.setpassword(password)
            rf.extractall(path=extract_root)
        except rarfile.PasswordRequired as exc:
            raise _PasswordRequiredError("需要密码") from exc
        except rarfile.BadRarFile as exc:
            if "password" in str(exc).lower():
                raise _PasswordRequiredError("密码错误") from exc
            raise _ArchiveFatalError(f"RAR 损坏:{exc!s}") from exc

    _walk_extracted_dir(
        extract_root=extract_root,
        depth=depth,
        counters=counters,
        on_child=on_child,
        bidder_id=bidder_id,
        source_archive_name=source_archive_name,
        password=password,
    )


def _walk_extracted_dir(
    *,
    extract_root: Path,
    depth: int,
    counters: dict[str, int],
    on_child: Callable[[BidDocument], None],
    bidder_id: int,
    source_archive_name: str,
    password: str | None,
) -> None:
    """7z/rar 一次性 extractall 后,扫描产物目录建 child rows + 处理嵌套。"""
    for path in extract_root.rglob("*"):
        if path.is_dir():
            continue
        # 打包垃圾(7z/rar 路径;相对 extract_root 判定)
        relative_for_junk = str(path.relative_to(extract_root))
        if is_junk_entry(relative_for_junk):
            try:
                path.unlink()
            except OSError:
                pass
            counters["junk_skipped"] = counters.get("junk_skipped", 0) + 1
            continue
        counters["count"] += 1
        ok, reason = check_count_budget(counters["count"])
        if not ok:
            raise _ArchiveFatalError(reason)

        size = path.stat().st_size
        counters["bytes"] += size
        ok, reason = check_size_budget(counters["bytes"])
        if not ok:
            raise _ArchiveFatalError(reason)

        # 算 MD5
        md5 = hashlib.md5(usedforsecurity=False)
        with path.open("rb") as fp:
            for chunk in iter(lambda: fp.read(64 * 1024), b""):
                md5.update(chunk)
        md5_hex = md5.hexdigest()

        relative = str(path.relative_to(extract_root))
        ext = path.suffix.lower()

        # 嵌套
        if ext in NESTED_ARCHIVE_EXTENSIONS:
            ok, reason = check_nesting_depth(depth + 1)
            if not ok:
                _emit_skipped_child(
                    on_child=on_child,
                    bidder_id=bidder_id,
                    file_name=path.name,
                    relative_path=relative,
                    reason=reason,
                    source_archive=source_archive_name,
                    file_size=size,
                )
                continue
            try:
                _sync_extract(
                    archive_path=path,
                    archive_ext=ext,
                    extract_root=path.parent / path.stem,
                    password=password,
                    depth=depth + 1,
                    counters=counters,
                    on_child=on_child,
                    bidder_id=bidder_id,
                    source_archive_name=source_archive_name,
                )
            except _PasswordRequiredError:
                _emit_skipped_child(
                    on_child=on_child,
                    bidder_id=bidder_id,
                    file_name=path.name,
                    relative_path=relative,
                    reason="嵌套压缩包需要密码,已跳过",
                    source_archive=source_archive_name,
                    file_size=size,
                )
            except _ArchiveFatalError as exc:
                _emit_skipped_child(
                    on_child=on_child,
                    bidder_id=bidder_id,
                    file_name=path.name,
                    relative_path=relative,
                    reason=str(exc)[:200],
                    source_archive=source_archive_name,
                    file_size=size,
                )
            continue

        if ext in EXTRACTABLE_FILE_EXTENSIONS:
            child = BidDocument(
                bidder_id=bidder_id,
                file_name=path.name,
                file_path=str(path),
                file_size=size,
                file_type=ext,
                md5=md5_hex,
                parse_status="extracted",
                parse_error=None,
                source_archive=source_archive_name,
            )
        else:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            child = BidDocument(
                bidder_id=bidder_id,
                file_name=path.name,
                file_path=str(path),
                file_size=size,
                file_type=ext or ".unknown",
                md5=md5_hex,
                parse_status="skipped",
                parse_error=f"暂不支持 {ext} 格式",
                source_archive=source_archive_name,
            )
        on_child(child)


def _emit_skipped_child(
    *,
    on_child: Callable[[BidDocument], None],
    bidder_id: int,
    file_name: str,
    relative_path: str,
    reason: str,
    source_archive: str,
    file_size: int,
) -> None:
    """跳过条目仍写一条 bid_documents,parse_status=skipped + 原因。

    md5 用 file_name + reason 算个稳定 hash,保证 UNIQUE(bidder_id, md5) 不冲突。
    """
    pseudo_md5 = hashlib.md5(
        f"skip::{bidder_id}::{relative_path}::{reason}".encode(),
        usedforsecurity=False,
    ).hexdigest()
    on_child(
        BidDocument(
            bidder_id=bidder_id,
            file_name=file_name,
            file_path=relative_path,
            file_size=file_size,
            file_type=Path(file_name).suffix.lower() or ".unknown",
            md5=pseudo_md5,
            parse_status="skipped",
            parse_error=reason,
            source_archive=source_archive,
        )
    )


# 抑制 ruff 对 imported but unused 的报警(Awaitable 留作 type hint 用)
_ = Awaitable

__all__ = ["extract_archive", "trigger_extract"]
