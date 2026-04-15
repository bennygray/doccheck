"""L1 - anomaly_impl/scorer (C12)"""

from __future__ import annotations

from app.services.detect.agents.anomaly_impl.models import (
    AnomalyOutlier,
    DetectionResult,
)
from app.services.detect.agents.anomaly_impl.scorer import compute_score


def _outlier(dev: float, bid: int = 1) -> AnomalyOutlier:
    return AnomalyOutlier(
        bidder_id=bid, total_price=70.0, deviation=dev, direction="low"
    )


def test_no_outliers_zero():
    result = DetectionResult(mean=100.0, outliers=[])
    assert compute_score(result) == 0.0


def test_one_outlier_35pct():
    """1 outlier 偏 35% → 30 + 35 = 65。"""
    result = DetectionResult(mean=93.0, outliers=[_outlier(-0.35)])
    assert compute_score(result) == 65.0


def test_two_outliers_capped():
    """2 outliers 最大偏 40% → 60 + 40 = 100(上限)。"""
    result = DetectionResult(
        mean=80.0, outliers=[_outlier(-0.35, 1), _outlier(-0.40, 2)]
    )
    assert compute_score(result) == 100.0


def test_three_outliers_capped():
    """3 outliers 即使偏离很小也到 100(3*30=90,再加最大偏离)。"""
    result = DetectionResult(
        mean=80.0,
        outliers=[
            _outlier(-0.30, 1),
            _outlier(-0.30, 2),
            _outlier(-0.32, 3),
        ],
    )
    # 90 + 32 = 122 → capped 100
    assert compute_score(result) == 100.0


def test_max_abs_uses_larger():
    """公式用 max(|dev|),不是平均。"""
    result = DetectionResult(
        mean=80.0, outliers=[_outlier(-0.30, 1), _outlier(-0.50, 2)]
    )
    # 60 + 50 = 110 → 100
    assert compute_score(result) == 100.0
