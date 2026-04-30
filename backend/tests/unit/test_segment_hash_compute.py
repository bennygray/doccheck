"""L1 - segment_hash 计算纯函数单测 (detect-tender-baseline 1.13)

覆盖 spec detect-framework "segment_hash 段级哈希索引" Requirement Scenarios:
- parser 切段后批量计算 segment_hash(归一化复用 _normalize)
- 短段 segment_hash 守门(< 5 字 NULL)
- 历史段落 lazy 处理(NULL 段 baseline_resolver 跳过)
"""

from __future__ import annotations

import hashlib

from app.services.detect.agents.text_sim_impl.tfidf import _normalize
from app.services.parser.content import _compute_segment_hash


# ============================================================ 短段守门


def test_segment_hash_short_segment_returns_none():
    """归一化后字符长度 < 5 → 返 None,baseline_resolver lazy 跳过。"""
    assert _compute_segment_hash("投标人:") is None  # 4 字
    assert _compute_segment_hash("    ") is None  # 全空白
    assert _compute_segment_hash("") is None
    assert _compute_segment_hash("a") is None


def test_segment_hash_at_min_threshold_returns_hash():
    """归一化后字符长度 = 5 → 触发 hash(边界)。"""
    h = _compute_segment_hash("12345")
    assert h is not None
    assert len(h) == 64  # sha256 hexdigest


# ============================================================ 归一化口径


def test_segment_hash_nfkc_full_half_width_equivalent():
    """NFKC 归一化:全角/半角字符 hash 一致。"""
    h_full = _compute_segment_hash("ＡＢＣＤＥ")  # 全角
    h_half = _compute_segment_hash("ABCDE")  # 半角
    assert h_full == h_half


def test_segment_hash_whitespace_normalized():
    """\\s+ → ' ' 归一化:多空格 / tab / 换行视同单空格。"""
    h1 = _compute_segment_hash("hello world today")
    h2 = _compute_segment_hash("hello   world\t\ttoday")
    h3 = _compute_segment_hash("hello\nworld\n today")
    assert h1 == h2 == h3


def test_segment_hash_strip_leading_trailing():
    """strip 首尾空白:前后空格不影响 hash。"""
    h1 = _compute_segment_hash("hello world")
    h2 = _compute_segment_hash("  hello world  ")
    h3 = _compute_segment_hash("\nhello world\t")
    assert h1 == h2 == h3


# ============================================================ sha256 算法


def test_segment_hash_sha256_format():
    """hash = sha256 hexdigest(归一化后 utf-8 编码)"""
    text = "锂源（江苏）科技有限公司"
    h = _compute_segment_hash(text)
    expected = hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()
    assert h == expected


def test_segment_hash_distinct_text_distinct_hash():
    """不同文本(归一化后) → 不同 hash。"""
    h1 = _compute_segment_hash("段落 A 内容")
    h2 = _compute_segment_hash("段落 B 内容")
    assert h1 != h2
