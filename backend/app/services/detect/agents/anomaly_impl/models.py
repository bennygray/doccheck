"""C12 TypedDict 数据契约 (anomaly_impl)"""

from __future__ import annotations

from typing import TypedDict


class BidderPriceSummary(TypedDict):
    """单家 bidder 报价汇总(extractor 产出)。"""

    bidder_id: int
    bidder_name: str
    total_price: float


class AnomalyOutlier(TypedDict):
    """异常低价 outlier(detector 产出 + evidence 写入)。"""

    bidder_id: int
    total_price: float
    deviation: float
    direction: str


class DetectionResult(TypedDict):
    """detector.detect_outliers 返回值。"""

    mean: float
    outliers: list[AnomalyOutlier]


__all__ = ["BidderPriceSummary", "AnomalyOutlier", "DetectionResult"]
