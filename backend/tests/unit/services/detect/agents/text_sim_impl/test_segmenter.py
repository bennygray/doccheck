"""L1 - text_sim_impl.segmenter 单元测试 (C7)"""

from __future__ import annotations

from app.services.detect.agents.text_sim_impl.segmenter import (
    MIN_PARAGRAPH_CHARS,
    _merge_short_paragraphs,
)


def test_merge_short_paragraphs_empty():
    assert _merge_short_paragraphs([], MIN_PARAGRAPH_CHARS) == []


def test_merge_short_paragraphs_all_short_fit_in_one():
    texts = ["a" * 10, "b" * 10, "c" * 10]
    out = _merge_short_paragraphs(texts, 50)
    # 总计 30 字符,末尾残留 merge 到最后一段(无则单独返回)
    assert len(out) == 1
    assert "a" * 10 in out[0] and "b" * 10 in out[0]


def test_merge_short_paragraphs_long_passthrough():
    long_para = "x" * 100
    out = _merge_short_paragraphs([long_para, "y" * 5], 50)
    # long_para 立即 flush;"y"*5 残留 merge 到 last
    assert len(out) == 1
    assert out[0].startswith(long_para)
    assert "y" * 5 in out[0]


def test_merge_short_paragraphs_alternating():
    texts = ["a" * 30, "b" * 30, "c" * 100, "d" * 10]
    out = _merge_short_paragraphs(texts, 50)
    # 30+30 合并成 ≥50(会被换行连接,实际 61 字符)→ flush
    # 100 立即 flush
    # 10 残留 → merge 到 last
    assert len(out) == 2
    assert "a" * 30 in out[0] and "b" * 30 in out[0]
    assert out[1].startswith("c" * 100)
    assert "d" * 10 in out[1]


def test_merge_short_paragraphs_strips_whitespace():
    out = _merge_short_paragraphs(["  hello  ", "\nworld\n"], 5)
    # 首段 strip 后 "hello"=5 ≥ threshold,flush
    assert out[0] == "hello"
    # world 残留,merge 到 last
    assert "world" in out[-1]
