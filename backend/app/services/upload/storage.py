"""C4 upload service - 落盘 + MD5 (D3 决策)。

边界:
- 只负责把 ``UploadFile`` 流式落盘到 ``uploads/<pid>/<bid>/<md5[:16]>_<safe_name>``
- 计算 MD5(单遍流式)与总字节数,与文件名一并返回
- 不做格式校验(那是 validator 的职责);不解压(那是 extract 的职责)

实现要点:
- 单遍流:边写边算 MD5,避免读两次大文件
- 原子写:先落到 ``.partial`` 临时文件,fsync 后 rename 到最终路径,异常时 unlink 掉残留
- 安全文件名:剥离路径分量(防 ``../``)、空白与控制字符替换为 ``_``,长度截到 240 给 hash 前缀留空间
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings

# 单次 read 块大小:1 MiB 在 500 MB 上限下约 500 次循环,内存友好
_CHUNK_BYTES = 1 * 1024 * 1024

# 文件名长度上限:文件系统通常 255,留 16 字节给 md5 前缀 + ``_`` 分隔符
_MAX_NAME_LEN = 240

# 控制字符 / 路径分隔符 / Windows 保留字符集中替换
_UNSAFE_NAME_RE = re.compile(r'[\x00-\x1f\\/:*?"<>|]+')


def _safe_basename(filename: str) -> str:
    """从用户上传文件名提取出可安全落盘的 basename。

    - 取 ``Path(...).name`` 去掉任何路径分量(防 zip-slip 风格的 ``../``)
    - 控制字符 / 路径分隔符 / Windows 保留字符 → ``_``
    - 多个连续 ``_`` 合并;两端 ``_.`` 去掉
    - 截断到 ``_MAX_NAME_LEN``;若全空则给一个兜底名
    """
    base = Path(filename).name
    base = _UNSAFE_NAME_RE.sub("_", base)
    base = re.sub(r"_+", "_", base).strip("_. ")
    if not base:
        base = "archive"
    if len(base) > _MAX_NAME_LEN:
        # 保留扩展名(若有)
        suffix = Path(base).suffix[:16]
        stem = Path(base).stem[: _MAX_NAME_LEN - len(suffix)]
        base = f"{stem}{suffix}"
    return base


async def save_archive(
    project_id: int,
    bidder_id: int,
    upload_file: UploadFile,
) -> tuple[Path, str, int]:
    """流式落盘 + 计算 MD5。

    Args:
        project_id: 用于路径分桶
        bidder_id: 用于路径分桶
        upload_file: FastAPI multipart 提取出的 ``UploadFile``;调用方需保证
            已通过 ``validator.validate_archive_file`` 的扩展名/魔数/大小校验

    Returns:
        ``(final_path, md5_hex, total_bytes)``

    Raises:
        OSError: 磁盘写入失败 / 目录创建失败;调用方决定是否清理残留 DB 行
    """
    # 用 resolve() 转绝对路径,避免 DB 存的相对路径在不同 cwd 启动时找不到文件
    target_dir = (
        Path(settings.upload_dir) / str(project_id) / str(bidder_id)
    ).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _safe_basename(upload_file.filename or "archive")
    # 临时文件:落盘期间用 ``.partial`` 后缀,完成后再 rename;
    # 用 PID + 原名做前缀避免同 bidder 并发上传冲突
    partial_path = target_dir / f".{os.getpid()}_{safe_name}.partial"

    md5 = hashlib.md5(usedforsecurity=False)
    total_bytes = 0

    # 关键:无论成功失败都要清残留;成功路径在 rename 后置 None 跳过 unlink
    cleanup_path: Path | None = partial_path
    try:
        # SpooledTemporaryFile 已经在内存或临时文件里;UploadFile.read() 是 async
        # 单遍循环:read → md5.update → write,内存只持单 chunk
        with partial_path.open("wb") as fp:
            while True:
                chunk = await upload_file.read(_CHUNK_BYTES)
                if not chunk:
                    break
                md5.update(chunk)
                fp.write(chunk)
                total_bytes += len(chunk)
            fp.flush()
            os.fsync(fp.fileno())

        md5_hex = md5.hexdigest()
        final_path = target_dir / f"{md5_hex[:16]}_{safe_name}"

        # 同 bidder 内 MD5 去重的 DB UNIQUE 已挡住正常重复;此处仅防"不同请求
        # 但同 MD5 + 同 safe_name"刚好碰撞 → 直接覆盖即可(内容字节相同)
        os.replace(partial_path, final_path)
        cleanup_path = None
        return final_path, md5_hex, total_bytes
    finally:
        if cleanup_path is not None and cleanup_path.exists():
            try:
                cleanup_path.unlink()
            except OSError:
                # 清不掉的残留留给运维;不掩盖原异常
                pass


async def save_tender_archive(
    project_id: int,
    tender_id: int,
    upload_file: UploadFile,
) -> tuple[Path, str, int]:
    """detect-tender-baseline D1/D7:tender 招标文件流式落盘 + 计算 MD5。

    与 ``save_archive`` 相同的流式 + 原子写 + safe_basename 行为,仅落盘路径不同:
    ``uploads/<pid>/tender/<tender_id>/<md5[:16]>_<safe_name>``

    Args:
        project_id: 用于路径分桶
        tender_id: 用于路径分桶(替代 bidder_id 的位置)
        upload_file: 已通过 ``validate_archive_file`` 的 UploadFile

    Returns:
        ``(final_path, md5_hex, total_bytes)``

    Raises:
        OSError: 磁盘写入失败 / 目录创建失败
    """
    target_dir = (
        Path(settings.upload_dir) / str(project_id) / "tender" / str(tender_id)
    ).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _safe_basename(upload_file.filename or "tender_archive")
    partial_path = target_dir / f".{os.getpid()}_{safe_name}.partial"

    md5 = hashlib.md5(usedforsecurity=False)
    total_bytes = 0

    cleanup_path: Path | None = partial_path
    try:
        with partial_path.open("wb") as fp:
            while True:
                chunk = await upload_file.read(_CHUNK_BYTES)
                if not chunk:
                    break
                md5.update(chunk)
                fp.write(chunk)
                total_bytes += len(chunk)
            fp.flush()
            os.fsync(fp.fileno())

        md5_hex = md5.hexdigest()
        final_path = target_dir / f"{md5_hex[:16]}_{safe_name}"
        os.replace(partial_path, final_path)
        cleanup_path = None
        return final_path, md5_hex, total_bytes
    finally:
        if cleanup_path is not None and cleanup_path.exists():
            try:
                cleanup_path.unlink()
            except OSError:
                pass


__all__ = ["save_archive", "save_tender_archive"]
