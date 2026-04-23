"""L2 - macOS 打包 zip 的端到端 extract 行为
(fix-mac-packed-zip-parsing 4.1)。

覆盖三件事一起生效:
- 打包垃圾(__MACOSX/._x / .DS_Store / ~$x.docx / Thumbs.db)静默丢弃,不写盘
  也不产生 bid_documents 行
- UTF-8 字节但 ZIP flag=0 的文件名正确还原为中文(不再是 "Σ╛¢σ║öσòåA/...")
- 归档行 `parse_error` 含"已过滤 N 个"审计留痕

手工构造 ZIP 字节流(Python stdlib zipfile 对非 ASCII 文件名会强制置位 bit 11,
无法原生模拟 macOS 无 flag 场景;只能按 ZIP 格式手写本地文件头+中心目录+EOCD)。
"""

from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.services.extract import extract_archive

from ..fixtures.archive_fixtures import md5_of
from ._c4_helpers import seed_archive_doc, seed_bidder, seed_project, seed_user


_DOCX_DUMMY = b"PK\x03\x04dummy-docx-content"


def _zip_with_raw_utf8_bytes_no_flag(
    entries: list[tuple[bytes, bytes]], out: Path
) -> Path:
    """手工构造 zip:filename 字段是原始 UTF-8 字节,flag bit 11 = 0。

    entries: [(utf8_filename_bytes, content_bytes), ...]
    """
    from io import BytesIO

    buf = BytesIO()
    offsets: list[int] = []

    for filename_bytes, content in entries:
        offsets.append(buf.tell())
        crc = zlib.crc32(content) & 0xFFFFFFFF
        local_header = struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,
            20,
            0x0000,  # flag bits — 不置 0x800
            0,  # stored
            0,
            0,
            crc,
            len(content),
            len(content),
            len(filename_bytes),
            0,
        )
        buf.write(local_header)
        buf.write(filename_bytes)
        buf.write(content)

    central_offset = buf.tell()
    for (filename_bytes, content), offset in zip(entries, offsets):
        crc = zlib.crc32(content) & 0xFFFFFFFF
        central_header = struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20,
            20,
            0x0000,
            0,
            0,
            0,
            crc,
            len(content),
            len(content),
            len(filename_bytes),
            0,
            0,
            0,
            0,
            0,
            offset,
        )
        buf.write(central_header)
        buf.write(filename_bytes)

    central_size = buf.tell() - central_offset
    eocd = struct.pack(
        "<IHHHHIIH",
        0x06054B50,
        0,
        0,
        len(entries),
        len(entries),
        central_size,
        central_offset,
        0,
    )
    buf.write(eocd)
    out.write_bytes(buf.getvalue())
    return out


def _mac_packed_zip(out: Path) -> Path:
    """模拟 macOS Archive Utility 打包的目录内容。
    包含:1 份真 docx + 若干 macOS/Office 垃圾,全部 UTF-8 无 flag。
    """
    real_name = "供应商A/江苏锂源一期-技术标-2025.12.29.docx".encode("utf-8")
    apple_double = (
        "__MACOSX/供应商A/._江苏锂源一期-技术标-2025.12.29.docx".encode("utf-8")
    )
    ds_store = "供应商A/.DS_Store".encode("utf-8")
    apple_double_ds = "__MACOSX/供应商A/._.DS_Store".encode("utf-8")
    office_lock = "供应商A/~$江苏锂源一期-技术标-2025.12.29.docx".encode("utf-8")
    office_tilde_crash = "供应商A/.~江苏锂源一期-技术标-2025.12.29.docx".encode(
        "utf-8"
    )
    thumbs = "供应商A/Thumbs.db".encode("utf-8")

    entries = [
        (real_name, _DOCX_DUMMY),
        (apple_double, b"AppleDouble-resource-fork-stub"),
        (ds_store, b"DS_Store-bytes"),
        (apple_double_ds, b"AppleDouble-DS-stub"),
        (office_lock, b"~$ office lock stub"),
        (office_tilde_crash, b".~ crash backup"),
        (thumbs, b"thumbs-db-stub"),
    ]
    return _zip_with_raw_utf8_bytes_no_flag(entries, out)


@pytest.fixture(autouse=True)
def _disable_auto_extract_and_pipeline():
    prev_e = os.environ.get("INFRA_DISABLE_EXTRACT")
    prev_p = os.environ.get("INFRA_DISABLE_PIPELINE")
    os.environ["INFRA_DISABLE_EXTRACT"] = "1"
    os.environ["INFRA_DISABLE_PIPELINE"] = "1"
    yield
    if prev_e is None:
        os.environ.pop("INFRA_DISABLE_EXTRACT", None)
    else:
        os.environ["INFRA_DISABLE_EXTRACT"] = prev_e
    if prev_p is None:
        os.environ.pop("INFRA_DISABLE_PIPELINE", None)
    else:
        os.environ["INFRA_DISABLE_PIPELINE"] = prev_p


@pytest.fixture
def isolated_dirs(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "extracted_dir", str(tmp_path / "extracted"))
    (tmp_path / "uploads").mkdir()
    (tmp_path / "extracted").mkdir()
    return tmp_path


async def _setup(
    *, owner_id: int, archive: Path
) -> tuple[Bidder, BidDocument]:
    project = await seed_project(owner_id=owner_id, name="P_mac")
    bidder = await seed_bidder(project_id=project.id)
    md5 = md5_of(archive)
    archive_row = await seed_archive_doc(
        bidder_id=bidder.id,
        archive_path=archive,
        md5=md5,
        file_name=archive.name,
        file_type=".zip",
    )
    return bidder, archive_row


async def _children_of(bidder_id: int) -> list[BidDocument]:
    """非顶层归档行的所有 bid_documents。"""
    async with async_session() as s:
        return (
            await s.execute(
                select(BidDocument).where(
                    BidDocument.bidder_id == bidder_id,
                    ~(
                        BidDocument.file_type.in_({".zip", ".7z", ".rar"})
                        & BidDocument.parse_status.in_(
                            {
                                "pending",
                                "extracting",
                                "extracted",
                                "partial",
                                "failed",
                                "needs_password",
                            }
                        )
                    ),
                )
            )
        ).scalars().all()


@pytest.mark.asyncio
async def test_mac_packed_zip_filters_junk_and_decodes_chinese(
    isolated_dirs,
) -> None:
    reviewer = await seed_user(username="rc_mac_pack_1")
    archive = _mac_packed_zip(isolated_dirs / "uploads" / "mac.zip")
    bidder, archive_row = await _setup(owner_id=reviewer.id, archive=archive)

    await extract_archive(bidder.id)

    children = await _children_of(bidder.id)
    # (a) 只剩 1 行真 docx
    assert len(children) == 1, (
        f"expected 1 real docx, got {len(children)}: "
        f"{[(c.file_name, c.parse_status) for c in children]}"
    )
    real = children[0]
    # (b) 文件名是正确中文
    assert real.file_name == "江苏锂源一期-技术标-2025.12.29.docx"
    assert real.file_type == ".docx"
    assert real.parse_status == "extracted"

    # (d) 归档行 parse_error 含"已过滤"
    async with async_session() as s:
        archive_after = await s.get(BidDocument, archive_row.id)
    msg = archive_after.parse_error or ""
    assert "已过滤" in msg, f"expected junk-skipped summary in parse_error, got: {msg!r}"
    # 6 个垃圾 entry 被丢:AppleDouble*2 + DS_Store + Office lock + Office tilde-crash + Thumbs.db
    assert "6" in msg


@pytest.mark.asyncio
async def test_pipeline_phase1_skips_archive_rows(isolated_dirs) -> None:
    """回归:pipeline 的 `_phase_extract_content` 必须按 file_type 过滤,不能把
    .zip 归档行也扔给 `extract_content` 处理(否则会被标成
    `未知文件类型 .zip` 并覆盖掉 extract 阶段写入的"已过滤 N 个"审计
    留痕)。(fix-mac-packed-zip-parsing 端到端修复)"""
    from app.services.parser.pipeline.run_pipeline import _phase_extract_content

    reviewer = await seed_user(username="rc_mac_pack_3")
    archive = _mac_packed_zip(isolated_dirs / "uploads" / "mac.zip")
    bidder, archive_row = await _setup(owner_id=reviewer.id, archive=archive)
    await extract_archive(bidder.id)

    # 确认 extract 阶段的审计留痕已入库
    async with async_session() as s:
        before = await s.get(BidDocument, archive_row.id)
    assert "已过滤" in (before.parse_error or "")
    assert before.parse_status == "extracted"

    # 走 pipeline phase1
    await _phase_extract_content(bidder.id)

    # 归档行应保持不变(phase1 按 file_type in docx/xlsx 过滤)
    async with async_session() as s:
        after = await s.get(BidDocument, archive_row.id)
    assert after.parse_status == "extracted", (
        f"phase1 不该碰 .zip 归档行,status 变成 {after.parse_status}"
    )
    assert "已过滤" in (after.parse_error or ""), (
        f"审计留痕被 phase1 覆盖了: {after.parse_error!r}"
    )


@pytest.mark.asyncio
async def test_mac_packed_zip_no_macosx_on_disk(isolated_dirs) -> None:
    """物理文件层面也不该有 __MACOSX 或 ._* 文件落盘。"""
    reviewer = await seed_user(username="rc_mac_pack_2")
    archive = _mac_packed_zip(isolated_dirs / "uploads" / "mac.zip")
    bidder, _ = await _setup(owner_id=reviewer.id, archive=archive)

    await extract_archive(bidder.id)

    extract_root = Path(settings.extracted_dir) / str(bidder.project_id) / str(
        bidder.id
    )
    disk_files = [p for p in extract_root.rglob("*") if p.is_file()]
    disk_names = [p.name for p in disk_files]
    # 不能含 __MACOSX 目录下任何文件
    assert not any(
        "__MACOSX" in str(p.relative_to(extract_root)) for p in disk_files
    ), f"__MACOSX entries leaked to disk: {disk_files}"
    # 不能含以 ._ 开头的文件
    assert not any(n.startswith("._") for n in disk_names), (
        f"AppleDouble files leaked to disk: {disk_names}"
    )
    # 不能含 .DS_Store / Thumbs.db / ~$*
    assert ".DS_Store" not in disk_names
    assert "Thumbs.db" not in disk_names
    assert not any(n.startswith("~$") or n.startswith(".~") for n in disk_names)
