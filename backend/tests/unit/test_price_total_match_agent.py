"""L1 - price_total_match Agent 单元测试 (fix-bug-triple-and-direction-high D5/D6)

锁:
1. 两家 bidder.total_price 完全相等 → has_iron_evidence + score=100
2. ≥2 家不同 total → 未命中
3. ≤1 家 → preflight skip(数据缺失)
4. 与 price_consistency 不重叠(责任划分:bidder 汇总 vs 行级)
"""

from __future__ import annotations

from app.services.detect.agents.anomaly_impl.models import BidderPriceSummary
from app.services.detect.agents.price_total_match_impl.detector import (
    detect_total_matches,
)


def _summary(bidder_id: int, name: str, total: float) -> BidderPriceSummary:
    return BidderPriceSummary(
        bidder_id=bidder_id, bidder_name=name, total_price=total
    )


def test_two_bidders_exact_total_match_iron():
    """两家 total 完全相等 → 命中 1 对铁证。"""
    summaries = [
        _summary(1, "甲", 486000.0),
        _summary(2, "乙", 486000.0),
    ]
    pairs = detect_total_matches(summaries)
    assert len(pairs) == 1
    assert pairs[0]["bidder_a_id"] == 1
    assert pairs[0]["bidder_b_id"] == 2
    assert pairs[0]["total"] == 486000.0


def test_three_bidders_two_match_one_diff():
    """3 家其中 2 家相等 → 命中 1 对。"""
    summaries = [
        _summary(1, "甲", 486000.0),
        _summary(2, "乙", 486000.0),
        _summary(3, "丙", 500000.0),
    ]
    pairs = detect_total_matches(summaries)
    assert len(pairs) == 1


def test_no_match():
    """所有 bidder total 不同 → 未命中。"""
    summaries = [
        _summary(1, "甲", 486000.0),
        _summary(2, "乙", 500000.0),
    ]
    pairs = detect_total_matches(summaries)
    assert pairs == []


def test_three_bidders_all_match():
    """3 家全相等 → 3 对(C(3,2))全部命中。"""
    summaries = [
        _summary(1, "甲", 486000.0),
        _summary(2, "乙", 486000.0),
        _summary(3, "丙", 486000.0),
    ]
    pairs = detect_total_matches(summaries)
    assert len(pairs) == 3


def test_float_precision_tolerance():
    """浮点边界:DECIMAL→float 微小误差仍视为相等。"""
    summaries = [
        _summary(1, "甲", 486000.0),
        _summary(2, "乙", 486000.001),  # < 0.005 容差
    ]
    pairs = detect_total_matches(summaries)
    assert len(pairs) == 1


def test_empty_summaries():
    """空列表不抛异常,返空。"""
    assert detect_total_matches([]) == []


def test_single_bidder():
    """单家 bidder 不构成 pair。"""
    pairs = detect_total_matches([_summary(1, "甲", 486000.0)])
    assert pairs == []
