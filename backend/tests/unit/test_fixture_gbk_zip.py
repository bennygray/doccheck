"""L1 - make_gbk_zip 实际产出验证 (harden-async-infra N6)

旧 `make_gbk_zip` 声称"flag=0 + GBK"实际产出"flag=0x800 + cp437(GBK 字节按
cp437 解码)" — Python stdlib `zipfile` 强制置位 bit 11 导致。本测试验证重写
后的 `make_gbk_zip` 真实产出符合 macOS GBK 包场景,确保
`fix-mac-packed-zip-parsing` 的自动化回归真生效。

同时双侧参数化验证 `build_zip_bytes(flag_bits=0 vs 0x800)`(reviewer L1)。
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

import pytest

from tests.fixtures.archive_fixtures import make_gbk_zip
from tests.fixtures.zip_bytes import build_zip_bytes


def _parse_local_header_flag(zip_bytes: bytes) -> tuple[int, bytes]:
    """解析首个 local file header,返 (flag_bits, filename_bytes)。"""
    # Local file header fmt:
    #   <I(sig) H(ver) H(flag) H(method) H(time) H(date) I(crc) I(csz) I(usz) H(fnlen) H(extra)
    sig, _ver, flag, _method, _time, _date, _crc, _csz, _usz, fn_len, _extra = (
        struct.unpack("<IHHHHHIIIHH", zip_bytes[:30])
    )
    assert sig == 0x04034B50, f"Not a ZIP signature: {hex(sig)}"
    filename_bytes = zip_bytes[30 : 30 + fn_len]
    return flag, filename_bytes


def test_make_gbk_zip_has_flag_zero_and_gbk_name():
    """harden-async-infra N6 核心断言:make_gbk_zip 产出真实符合
    "bit 11=0 + GBK 文件名字节",而非旧 `zipfile` 版本的 "bit 11=1 + cp437"。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "gbk.zip"
        make_gbk_zip(out)

        zip_bytes = out.read_bytes()
        flag, filename_bytes = _parse_local_header_flag(zip_bytes)

        # flag bit 11 MUST = 0(macOS GBK 场景特征)
        assert (flag & 0x800) == 0, (
            f"make_gbk_zip 的 flag bit 11 应为 0(GBK no-flag 场景),"
            f"实际 flag={hex(flag)}"
        )

        # filename 字节 MUST 按 GBK 解码成功,且是 "投标文件.docx"
        decoded = filename_bytes.decode("gbk")
        assert decoded == "投标文件.docx", (
            f"make_gbk_zip 文件名 GBK 解码后应为 '投标文件.docx',实际 {decoded!r}"
        )

        # 关键反向断言:按 UTF-8 解码应**失败或不等于**原文本(GBK 字节不是合法 UTF-8)
        try:
            utf8_decoded = filename_bytes.decode("utf-8")
            assert utf8_decoded != "投标文件.docx", (
                "GBK 字节不应按 UTF-8 解成原文本,否则 fixture 实为 UTF-8"
            )
        except UnicodeDecodeError:
            pass  # 预期路径:GBK 字节对 UTF-8 解码会抛


@pytest.mark.parametrize(
    "flag_bits,encoding,expect_flag_bit_11",
    [
        (0, "gbk", False),
        (0x800, "utf-8", True),
    ],
)
def test_build_zip_bytes_symmetric_flag_control(
    flag_bits: int, encoding: str, expect_flag_bit_11: bool
) -> None:
    """reviewer L1:build_zip_bytes 支持 flag_bits 参数化,flag=0 和 flag=0x800
    对称都可产出,防止 helper 退化为只能造一侧。"""
    filename_bytes = "测试.docx".encode(encoding)
    zip_bytes = build_zip_bytes(
        [(filename_bytes, b"payload")],
        flag_bits=flag_bits,
    )
    actual_flag, actual_filename = _parse_local_header_flag(zip_bytes)

    has_bit_11 = bool(actual_flag & 0x800)
    assert has_bit_11 == expect_flag_bit_11, (
        f"build_zip_bytes(flag_bits={hex(flag_bits)}): bit 11 "
        f"期望 {expect_flag_bit_11},实际 {has_bit_11}"
    )
    assert actual_filename == filename_bytes, (
        f"filename 字节不应被改写;期望 {filename_bytes!r},实际 {actual_filename!r}"
    )
    assert actual_filename.decode(encoding) == "测试.docx"
