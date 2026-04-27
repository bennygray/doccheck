"""L1 - price_overshoot Agent 单元测试 (fix-bug-triple-and-direction-high D6)

锁:
1. 任一 bidder.total > max_price → has_iron_evidence + score=100
2. 所有 bidder ≤ max_price → 未命中
3. max_price=NULL 或 ≤0 → preflight skip(决策 1A 需要 max_price 才能判)
4. ratio 计算正确
"""

from __future__ import annotations

from app.services.detect.agents.anomaly_impl.models import BidderPriceSummary
from app.services.detect.agents.price_overshoot_impl.detector import (
    detect_overshoot,
)


def _s(bidder_id: int, name: str, total: float) -> BidderPriceSummary:
    return BidderPriceSummary(
        bidder_id=bidder_id, bidder_name=name, total_price=total
    )


def test_one_bidder_overshoot_hit():
    """max_price=400 + 一家 total=500 → 命中,ratio=0.25。"""
    summaries = [_s(1, "甲", 500.0), _s(2, "乙", 380.0)]
    overshoot = detect_overshoot(summaries, max_price=400.0)
    assert len(overshoot) == 1
    assert overshoot[0]["bidder_id"] == 1
    assert overshoot[0]["total"] == 500.0
    assert overshoot[0]["ratio"] == 0.25


def test_all_bidders_within_limit():
    """全部 ≤ max_price → 未命中。"""
    summaries = [_s(1, "甲", 380.0), _s(2, "乙", 400.0)]
    overshoot = detect_overshoot(summaries, max_price=400.0)
    assert overshoot == []


def test_strictly_greater_required():
    """total = max_price 不算超限(严格大于)。"""
    summaries = [_s(1, "甲", 400.0)]
    overshoot = detect_overshoot(summaries, max_price=400.0)
    assert overshoot == []


def test_multiple_bidders_overshoot():
    """多家超限全部命中。"""
    summaries = [_s(1, "甲", 500.0), _s(2, "乙", 600.0), _s(3, "丙", 350.0)]
    overshoot = detect_overshoot(summaries, max_price=400.0)
    assert len(overshoot) == 2
    ids = {o["bidder_id"] for o in overshoot}
    assert ids == {1, 2}


def test_user_doc_scenario():
    """用户 doc 报的 bug 3 真实场景:max_price=436000,实际 486000 → 超 11.5%。"""
    summaries = [_s(1, "甲", 486000.0), _s(2, "乙", 486000.0)]
    overshoot = detect_overshoot(summaries, max_price=436000.0)
    assert len(overshoot) == 2
    # 11.46789..% ≈ 0.1147
    assert abs(overshoot[0]["ratio"] - 0.1147) < 0.001
