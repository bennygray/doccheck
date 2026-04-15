"""L1 - anomaly_impl/detector (C12)"""

from __future__ import annotations

import logging

from app.services.detect.agents.anomaly_impl.config import AnomalyConfig
from app.services.detect.agents.anomaly_impl.detector import detect_outliers
from app.services.detect.agents.anomaly_impl.models import BidderPriceSummary


def _s(bidder_id: int, total: float, name: str = None) -> BidderPriceSummary:
    return BidderPriceSummary(
        bidder_id=bidder_id,
        bidder_name=name or f"B{bidder_id}",
        total_price=total,
    )


def _cfg(threshold=0.30, direction="low") -> AnomalyConfig:
    return AnomalyConfig(
        enabled=True,
        min_sample_size=3,
        deviation_threshold=threshold,
        direction=direction,
        baseline_enabled=False,
        max_bidders=50,
        weight=1.0,
    )


def test_empty_summaries_returns_zero_mean():
    result = detect_outliers([], _cfg())
    assert result["mean"] == 0.0
    assert result["outliers"] == []


def test_all_zero_prices_no_division_error():
    summaries = [_s(1, 0.0), _s(2, 0.0), _s(3, 0.0)]
    result = detect_outliers(summaries, _cfg())
    assert result["mean"] == 0.0
    assert result["outliers"] == []


def test_35_percent_below_triggers():
    """5 家 [100,105,98,60,102],mean=93,D 偏离 -35.5% > 30% → outlier。"""
    summaries = [_s(1, 100), _s(2, 105), _s(3, 98), _s(4, 60), _s(5, 102)]
    result = detect_outliers(summaries, _cfg(threshold=0.30))
    assert abs(result["mean"] - 93.0) < 1e-6
    assert len(result["outliers"]) == 1
    out = result["outliers"][0]
    assert out["bidder_id"] == 4
    assert out["direction"] == "low"
    assert out["deviation"] < -0.30


def test_26_percent_below_not_triggers():
    """5 家 [100,105,98,70,102],mean=95,D 偏离 -26.3% < 30% → 不 outlier。"""
    summaries = [_s(1, 100), _s(2, 105), _s(3, 98), _s(4, 70), _s(5, 102)]
    result = detect_outliers(summaries, _cfg(threshold=0.30))
    assert len(result["outliers"]) == 0


def test_all_normal_no_outlier():
    summaries = [_s(1, 100), _s(2, 105), _s(3, 98), _s(4, 103), _s(5, 102)]
    result = detect_outliers(summaries, _cfg())
    assert len(result["outliers"]) == 0


def test_multiple_outliers():
    """2 家明显偏低(50 与 55),1 家正常 → 2 个 outlier。"""
    summaries = [_s(1, 100), _s(2, 105), _s(3, 50), _s(4, 55), _s(5, 102)]
    result = detect_outliers(summaries, _cfg(threshold=0.30))
    assert len(result["outliers"]) == 2
    ids = {o["bidder_id"] for o in result["outliers"]}
    assert ids == {3, 4}


def test_direction_high_fallback_to_low(caplog):
    """direction=high 本期未实现,fallback low + warn。"""
    summaries = [_s(1, 100), _s(2, 105), _s(3, 98), _s(4, 180), _s(5, 102)]
    # 1 家偏高 60% — 若实现了 high 会触发;本期 fallback 到 low 应无 outlier
    with caplog.at_level(logging.WARNING):
        result = detect_outliers(summaries, _cfg(direction="high"))
    assert len(result["outliers"]) == 0
    assert any(
        "direction='high' not implemented" in r.message
        for r in caplog.records
    )


def test_high_threshold_filter():
    """threshold=0.50,1 家偏低 35% → 不触发。"""
    summaries = [_s(1, 100), _s(2, 105), _s(3, 98), _s(4, 60), _s(5, 102)]
    result = detect_outliers(summaries, _cfg(threshold=0.50))
    assert len(result["outliers"]) == 0


def test_low_threshold_catches_more():
    """threshold=0.10,偏低 10% 以上全部告警。"""
    summaries = [_s(1, 100), _s(2, 105), _s(3, 85), _s(4, 80), _s(5, 102)]
    # mean = 94.4;各偏离:+5.9% / +11.2% / -9.9% / -15.2% / +8.0%
    # threshold=0.10 → 仅 bidder 4 (-15%) 触发
    result = detect_outliers(summaries, _cfg(threshold=0.10))
    assert len(result["outliers"]) == 1
    assert result["outliers"][0]["bidder_id"] == 4
