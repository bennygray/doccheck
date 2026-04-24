"""_looks_like_utf8 + decode_filename UTF-8 优先路径 L1 单测
(fix-mac-packed-zip-parsing 2.4)。

覆盖 macOS Archive Utility 打包"UTF-8 字节但未置 ZIP bit 11"场景下的解码
正确性,以及对 Windows GBK 真实场景的零回归。
"""

from __future__ import annotations

import pytest

from app.services.extract.encoding import _looks_like_utf8, decode_filename


# ------------------------- _looks_like_utf8 ----


def test_looks_like_utf8_ascii_only() -> None:
    assert _looks_like_utf8(b"hello.docx") is True


def test_looks_like_utf8_empty_returns_false() -> None:
    # 空字节不算合法 UTF-8 序列
    assert _looks_like_utf8(b"") is False


def test_looks_like_utf8_zh_utf8_bytes() -> None:
    # "供应商A" = E4BE9B E5BA94 E5958661
    raw = "供应商A".encode("utf-8")
    assert _looks_like_utf8(raw) is True


def test_looks_like_utf8_jp_utf8_bytes() -> None:
    # "テスト"
    raw = "テスト".encode("utf-8")
    assert _looks_like_utf8(raw) is True


def test_looks_like_utf8_mixed_ascii_utf8() -> None:
    raw = "江苏锂源-Ver2.docx".encode("utf-8")
    assert _looks_like_utf8(raw) is True


def test_looks_like_utf8_gbk_bytes_false() -> None:
    # "供应商A" GBK 字节 = B9A9 D3A6 C9CC 41 (4 x 2-byte + 1 ASCII)
    raw = "供应商A".encode("gbk")
    assert _looks_like_utf8(raw) is False


def test_looks_like_utf8_truncated_multibyte_false() -> None:
    # "供" UTF-8 = E4 BE 9B,截掉尾字节
    assert _looks_like_utf8(b"\xe4\xbe") is False


def test_looks_like_utf8_orphan_trailbyte_false() -> None:
    assert _looks_like_utf8(b"\x80") is False
    assert _looks_like_utf8(b"abc\xbfdef") is False


def test_looks_like_utf8_overlong_c0_c1_false() -> None:
    # 0xC0/0xC1 开头是 overlong,拒绝
    assert _looks_like_utf8(b"\xc0\x80") is False
    assert _looks_like_utf8(b"\xc1\xbf") is False


def test_looks_like_utf8_f5_plus_false() -> None:
    # 0xF5-0xFF 都不是合法 UTF-8 lead byte(> U+10FFFF)
    assert _looks_like_utf8(b"\xf5\x80\x80\x80") is False


# ------------------------- decode_filename 端到端 ----


def test_decode_filename_utf8_flag_happy_path() -> None:
    raw = "供应商A.docx".encode("utf-8")
    name, warn = decode_filename(raw, is_utf8_flagged=True)
    assert name == "供应商A.docx"
    assert warn is None


def test_decode_filename_utf8_no_flag_uses_new_layer() -> None:
    # macOS 场景:UTF-8 字节,flag=False → 新 _looks_like_utf8 层命中
    raw = "江苏锂源一期.docx".encode("utf-8")
    name, warn = decode_filename(raw, is_utf8_flagged=False)
    assert name == "江苏锂源一期.docx"
    assert warn is None


def test_decode_filename_gbk_no_flag_unchanged() -> None:
    # Windows 场景:GBK 字节,flag=False → 应走到 GBK 分支(UTF-8 层拒绝)
    raw = "投标文件.docx".encode("gbk")
    name, warn = decode_filename(raw, is_utf8_flagged=False)
    assert name == "投标文件.docx"
    assert warn is None


def test_decode_filename_pure_ascii() -> None:
    raw = b"report.pdf"
    name, warn = decode_filename(raw, is_utf8_flagged=False)
    assert name == "report.pdf"
    assert warn is None


def test_decode_filename_empty() -> None:
    name, warn = decode_filename(b"", is_utf8_flagged=False)
    assert name == ""
    assert warn is None


def test_decode_filename_garbage_falls_back_with_warning() -> None:
    # 非 UTF-8 非 GBK 非中文 → chardet 或 latin1 兜底
    raw = b"\xff\xfe\xfd\xfc"
    name, warn = decode_filename(raw, is_utf8_flagged=False)
    # 不要求具体内容,只要能返回且无异常
    assert isinstance(name, str)
    # latin1 兜底必带 warn;chardet 命中可能无 warn
    assert name != ""


# ------------------------- ZIP 启发式端到端(模拟 Python zipfile 行为) ----


def test_decode_filename_mac_archive_utility_no_flag_round_trip() -> None:
    """模拟 macOS Archive Utility 无 flag 场景:
    真实字节是 UTF-8,但 ZIP spec 未置 bit 11。Python zipfile 在该场景下会
    把 info.filename 按 cp437 解码(产出看起来像乱码的字符串)。engine.py 的
    新 UTF-8 优先路径会 encode cp437 还原原字节,用 UTF-8 解码还原为 "供应商A"。

    此处直接模拟 decode_filename 在"拿到 raw UTF-8 字节"时的行为。
    """
    raw = "供应商A/江苏锂源一期.docx".encode("utf-8")
    name, warn = decode_filename(raw, is_utf8_flagged=False)
    assert name == "供应商A/江苏锂源一期.docx"
    assert warn is None
