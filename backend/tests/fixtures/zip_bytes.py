"""精准控制 flag_bits / 编码的 ZIP 字节构造 helper (harden-async-infra N6)

Python stdlib `zipfile` 对非 ASCII 文件名会**强制置位 bit 11(UTF-8 flag)**,
无法原生模拟:
- macOS Archive Utility:UTF-8 字节但 flag=0
- Windows 旧系统:GBK 字节 flag=0
- 其他 bit 11 = 1 的 UTF-8 标准路径

本 helper 直接按 ZIP APPNOTE 手写本地文件头 + 中心目录 + EOCD,完全绕开 zipfile
的自动 flag 决策,由调用者显式传入 flag_bits 与已编码的 filename_bytes。

用途:
- `fix-mac-packed-zip-parsing` 的 L1 `test_engine_utf8_no_flag.py`
- `harden-async-infra N6` 重写后的 `make_gbk_zip`
- 未来任何需要精确字节布局的 ZIP 测试
"""

from __future__ import annotations

import struct
import zlib
from io import BytesIO


def build_zip_bytes(
    entries: list[tuple[bytes, bytes]],
    *,
    flag_bits: int,
) -> bytes:
    """手工构造 zip 字节流,filename 字段用原始字节、flag 精确控制。

    Args:
        entries: [(filename_bytes, content_bytes), ...];filename_bytes 已按目标
            编码 encode(utf-8 / gbk / cp437 等),本函数不做任何编码转换
        flag_bits: 本地 + 中心目录的 general purpose flag(0 = GBK/cp437 默认,
            0x800 = UTF-8 标准)。仅影响 metadata bit,不影响压缩行为

    Returns:
        完整 zip 字节流(单一 bytes 对象)

    Notes:
        - 采用 stored(不压缩)方法,简化 CRC 计算;不做大文件优化
        - 所有条目共用相同 flag_bits
    """
    buf = BytesIO()
    offsets: list[int] = []

    # --- 本地文件头(per entry) ---
    for filename_bytes, content in entries:
        offsets.append(buf.tell())
        crc = zlib.crc32(content) & 0xFFFFFFFF
        local_header = struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,       # signature PK\x03\x04
            20,                # version
            flag_bits & 0xFFFF,  # general purpose bit flag
            0,                 # method = stored
            0,                 # mod_time
            0,                 # mod_date
            crc,
            len(content),
            len(content),
            len(filename_bytes),
            0,                 # extra_len
        )
        buf.write(local_header)
        buf.write(filename_bytes)
        buf.write(content)

    # --- 中心目录 ---
    central_offset = buf.tell()
    for (filename_bytes, content), offset in zip(entries, offsets):
        crc = zlib.crc32(content) & 0xFFFFFFFF
        central_header = struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,        # signature
            20,                 # version made by
            20,                 # version needed
            flag_bits & 0xFFFF,
            0,                  # method
            0,                  # mod_time
            0,                  # mod_date
            crc,
            len(content),
            len(content),
            len(filename_bytes),
            0,                  # extra_len
            0,                  # comment_len
            0,                  # disk_number
            0,                  # internal_attrs
            0,                  # external_attrs
            offset,
        )
        buf.write(central_header)
        buf.write(filename_bytes)

    # --- EOCD ---
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
    return buf.getvalue()


__all__ = ["build_zip_bytes"]
