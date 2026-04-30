"""上传文件校验:扩展名 + 魔数 + 大小三道(D7 决策)。

抛业务异常,路由层捕获并映射 415 / 413。
"""

from __future__ import annotations

# stdlib only;magic 通过延迟 import,libmagic 缺失时 fallback 到扩展名
ARCHIVE_EXTENSIONS = frozenset({".zip", ".7z", ".rar"})
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024  # 500 MB

# 魔数白名单(extension → magic mime / 魔数前缀)
# 用前缀比对而非完整 mime 字符串,兼容 libmagic 不同版本输出
_EXPECTED_MIME_PREFIXES: dict[str, tuple[str, ...]] = {
    ".zip": ("application/zip", "application/x-zip"),
    ".7z": ("application/x-7z-compressed",),
    ".rar": ("application/x-rar", "application/vnd.rar"),
}

# 魔数前缀 fallback(libmagic 不可用时用文件头硬比对)
_MAGIC_BYTES: dict[str, tuple[bytes, ...]] = {
    ".zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".7z": (b"\x37\x7a\xbc\xaf\x27\x1c",),
    ".rar": (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"),
}


class UnsupportedMediaType(Exception):
    """文件类型不在白名单或魔数与扩展名不匹配。"""


class FileTooLarge(Exception):
    """文件大小超过上限。"""


def _guess_mime_with_magic(head: bytes) -> str | None:
    """尝试用 libmagic 识别 mime;不可用返回 None,调 caller fallback。"""
    try:
        import magic  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        m = magic.Magic(mime=True)
        return m.from_buffer(head)
    except Exception:
        # libmagic backend 异常(Windows 上可能没装好)→ fallback
        return None


def _validate_magic(extension: str, head: bytes) -> bool:
    """魔数校验:libmagic 优先,octet-stream 或不可用时 fallback 到字节头硬比对。

    libmagic 对小型 zip(如全 docx/xlsx 的小招标包)可能返 application/octet-stream
    "我不知道",此时不应直接判错,而应继续 fallback 字节头判定。
    """
    mime = _guess_mime_with_magic(head)
    if mime is not None and mime != "application/octet-stream":
        expected = _EXPECTED_MIME_PREFIXES.get(extension, ())
        return any(mime.startswith(p) for p in expected)

    # libmagic 不可用 或 返 octet-stream → fallback 字节头硬比对
    expected_bytes = _MAGIC_BYTES.get(extension, ())
    return any(head.startswith(b) for b in expected_bytes)


def validate_archive_file(
    *,
    filename: str,
    head_bytes: bytes,
    total_size: int,
) -> str:
    """对上传的压缩包做三道校验,返回归一化的小写扩展名。

    Args:
        filename: 上传文件原名(用于取扩展名)
        head_bytes: 文件首 N 字节(>=8 字节足够;魔数最长 6 字节)
        total_size: 文件总字节数

    Raises:
        UnsupportedMediaType: 扩展名不在白名单 或 魔数不匹配 → 415
        FileTooLarge: 文件 > 500MB → 413
    """
    # 1. 大小
    if total_size > MAX_ARCHIVE_BYTES:
        raise FileTooLarge(
            f"文件大小 {total_size} 字节超过限制 {MAX_ARCHIVE_BYTES}"
        )

    # 2. 扩展名
    if "." not in filename:
        raise UnsupportedMediaType("文件无扩展名")
    extension = "." + filename.rsplit(".", 1)[-1].lower()
    if extension not in ARCHIVE_EXTENSIONS:
        raise UnsupportedMediaType(
            f"扩展名 {extension} 不在白名单(允许 {sorted(ARCHIVE_EXTENSIONS)})"
        )

    # 3. 魔数
    if not _validate_magic(extension, head_bytes):
        raise UnsupportedMediaType(
            f"文件内容与扩展名 {extension} 不匹配(魔数校验失败)"
        )

    return extension


__all__ = [
    "ARCHIVE_EXTENSIONS",
    "MAX_ARCHIVE_BYTES",
    "FileTooLarge",
    "UnsupportedMediaType",
    "validate_archive_file",
]
