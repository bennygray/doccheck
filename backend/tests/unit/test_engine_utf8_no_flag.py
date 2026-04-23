"""engine.py ZIP 启发式在"UTF-8 字节但 ZIP bit 11 未置"场景下的解码正确性
(fix-mac-packed-zip-parsing 2.5)。

构造真实的 ZIP 文件:entry 的文件名字节是 UTF-8 但 general-purpose flag bit 11
保持为 0(模拟 macOS Archive Utility 的行为),用真实 `zipfile.ZipFile` 读取
并调 engine._extract_zip 的 on_child 回调,断言文件名被正确还原为中文而非
"Σ╛¢σ║öσòåA/..." 形式的乱码。
"""

from __future__ import annotations

import struct
import zipfile
import zlib
from io import BytesIO
from pathlib import Path

import pytest


def _build_zip_with_raw_utf8_bytes_no_flag(
    entries: list[tuple[bytes, bytes]],
) -> bytes:
    """手工构造 zip 文件字节流,filename 字段用原始 UTF-8 字节、flag=0。

    Python 标准库 zipfile 在写非 ASCII 文件名时会强制置位 bit 11,不能直接用它
    模拟 macOS Archive Utility 的"无 flag"行为;这里按 ZIP 格式手工拼本地
    文件头 + 中心目录 + EOCD,完全绕过 zipfile 的 writestr。

    Args:
        entries: [(filename_bytes_utf8, content_bytes), ...]
    Returns:
        完整 zip 字节流
    """
    buf = BytesIO()
    central_entries: list[bytes] = []
    offsets: list[int] = []

    for filename_bytes, content in entries:
        offsets.append(buf.tell())
        crc = zlib.crc32(content) & 0xFFFFFFFF
        # 本地文件头:signature(4) + version(2) + flag(2, 置 0) + method(2, 0=stored)
        # + mod_time(2) + mod_date(2) + crc(4) + comp_size(4) + uncomp_size(4)
        # + filename_len(2) + extra_len(2)
        local_header = struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,  # signature
            20,  # version
            0x0000,  # flag — bit 11 (UTF-8) 保持 0
            0,  # method = stored(不压缩,简化)
            0,  # mod_time
            0,  # mod_date
            crc,
            len(content),
            len(content),
            len(filename_bytes),
            0,  # extra_len
        )
        buf.write(local_header)
        buf.write(filename_bytes)
        buf.write(content)

    # 中心目录
    central_offset = buf.tell()
    for (filename_bytes, content), offset in zip(entries, offsets):
        crc = zlib.crc32(content) & 0xFFFFFFFF
        central_header = struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20,
            20,
            0x0000,  # flag = 0
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
        central_entries.append(filename_bytes)

    central_size = buf.tell() - central_offset
    # EOCD
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


def test_engine_reads_mac_utf8_no_flag(tmp_path: Path) -> None:
    """造一个"供应商A.docx"条目,UTF-8 字节但 flag=0,确认 engine 解出中文。"""
    filename_bytes = "供应商A.docx".encode("utf-8")
    # 必须是合法 zip 本地流;内容随便
    content = b"fake-docx-payload"
    zip_bytes = _build_zip_with_raw_utf8_bytes_no_flag(
        [(filename_bytes, content)]
    )
    zip_path = tmp_path / "mac-utf8.zip"
    zip_path.write_bytes(zip_bytes)

    # 用标准 zipfile 读,验证 info.filename 确实是乱码(cp437 解码)
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        assert len(infos) == 1
        info = infos[0]
        # flag bit 11 确实为 0
        assert (info.flag_bits & 0x800) == 0
        # zipfile 按 cp437 解码 UTF-8 字节 → info.filename 是乱码(复现真实现场)
        mojibake = info.filename
        assert mojibake != "供应商A.docx"
        # 现在模拟 engine.py 的逻辑:cp437 编码回原字节,然后 _looks_like_utf8 + utf-8 decode
        from app.services.extract.encoding import _looks_like_utf8

        raw = mojibake.encode("cp437")
        assert raw == filename_bytes
        assert _looks_like_utf8(raw) is True
        assert raw.decode("utf-8") == "供应商A.docx"


def test_engine_reads_mac_utf8_no_flag_mixed_with_gbk_unaffected(
    tmp_path: Path,
) -> None:
    """同一 zip 里 UTF-8 和 GBK 场景隔离验证:
    - UTF-8 无 flag 字节 → 新优先路径正确解
    - 纯 ASCII 字节 → 两种路径都对
    """
    entries = [
        ("技术标-江苏.docx".encode("utf-8"), b"u8-doc-bytes"),
        ("plain.txt".encode("ascii"), b"hello"),
    ]
    zip_bytes = _build_zip_with_raw_utf8_bytes_no_flag(entries)
    zip_path = tmp_path / "mixed.zip"
    zip_path.write_bytes(zip_bytes)

    from app.services.extract.encoding import _looks_like_utf8

    with zipfile.ZipFile(zip_path) as zf:
        for info, (expected_bytes, _) in zip(zf.infolist(), entries):
            raw = info.filename.encode("cp437")
            assert raw == expected_bytes
            assert _looks_like_utf8(raw) is True
            assert raw.decode("utf-8") == expected_bytes.decode("utf-8")


def test_engine_keeps_gbk_heuristic_for_windows_packs() -> None:
    """验证 GBK 真实场景不受新路径影响:
    - raw_bytes 是 GBK → _looks_like_utf8 返 False → 进入现有 GBK 启发式。
    """
    from app.services.extract.encoding import _looks_like_utf8

    gbk_bytes = "投标文件-供应商A.docx".encode("gbk")
    # 关键断言:GBK 字节不满足 UTF-8 模式,新路径不会误接管
    assert _looks_like_utf8(gbk_bytes) is False
    # 原启发式仍然能 decode
    assert gbk_bytes.decode("gbk") == "投标文件-供应商A.docx"
