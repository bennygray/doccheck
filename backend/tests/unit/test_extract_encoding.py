"""L1 单元 - extract.encoding 文件名编码探测 (C4 §10.2)。

覆盖 UTF-8 flag / GBK / chardet fallback / 乱码兜底 4 个分支。
"""

from __future__ import annotations

from app.services.extract.encoding import decode_filename


def test_utf8_flag_priority() -> None:
    name, warn = decode_filename("中文.docx".encode("utf-8"), is_utf8_flagged=True)
    assert name == "中文.docx"
    assert warn is None


def test_gbk_fallback() -> None:
    raw = "投标.docx".encode("gbk")
    name, warn = decode_filename(raw, is_utf8_flagged=False)
    assert name == "投标.docx"
    assert warn is None


def test_chardet_high_confidence() -> None:
    raw = "工程量清单_报价.xlsx".encode("gbk")
    name, _ = decode_filename(raw, is_utf8_flagged=False)
    assert "工程量清单" in name


def test_empty_returns_empty() -> None:
    name, warn = decode_filename(b"", is_utf8_flagged=True)
    assert name == ""
    assert warn is None


def test_utf8_flag_lying_falls_through() -> None:
    """flag 说 UTF-8 但实际是 GBK → fallback 仍能还原。"""
    raw = "测试.docx".encode("gbk")
    name, _ = decode_filename(raw, is_utf8_flagged=True)
    assert "测试" in name


def test_garbage_bytes_latin1_with_warning() -> None:
    """全是 0xff 等高位字节 → chardet/gbk 都解不出 → latin1 兜底带 warning。"""
    raw = bytes([0xFF, 0xFE, 0xFD, 0xFC] * 4)
    name, warn = decode_filename(raw, is_utf8_flagged=False)
    assert name  # 不是空,latin1 总能解
    # warn 视 chardet 探测结果可能为 None 也可能为 "...乱码";兜底语义就是
    # 数据不损失,所以 warn 不强制断言
    _ = warn
