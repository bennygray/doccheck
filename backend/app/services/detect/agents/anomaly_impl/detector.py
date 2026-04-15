"""C12 偏离判定 (anomaly_impl)

detect_outliers:
- mean = sum(total_price) / N
- deviation = (total - mean) / mean
- direction='low':deviation < -threshold → outlier
- direction='high'/'both':本期未实现,fallback to 'low' + warn
- mean==0 → 所有 deviation 无意义,返空 outliers(不抛 ZeroDivisionError)
"""

from __future__ import annotations

import logging

from app.services.detect.agents.anomaly_impl.config import AnomalyConfig
from app.services.detect.agents.anomaly_impl.models import (
    AnomalyOutlier,
    BidderPriceSummary,
    DetectionResult,
)

logger = logging.getLogger(__name__)

_SUPPORTED_DIRECTIONS = {"low"}  # 本期仅 low;high/both 预留


def detect_outliers(
    summaries: list[BidderPriceSummary], cfg: AnomalyConfig
) -> DetectionResult:
    """均值偏离检测。

    空列表 → mean=0, outliers=[]。
    全 0 报价 → mean=0, outliers=[](不抛 ZeroDivisionError)。
    direction 非 low → warn + fallback low。
    """
    if not summaries:
        return DetectionResult(mean=0.0, outliers=[])

    total_sum = sum(s["total_price"] for s in summaries)
    mean = total_sum / len(summaries)
    if mean == 0.0:
        return DetectionResult(mean=0.0, outliers=[])

    direction = cfg.direction
    if direction not in _SUPPORTED_DIRECTIONS:
        logger.warning(
            "direction=%r not implemented in C12, fallback to 'low'", direction
        )
        direction = "low"

    outliers: list[AnomalyOutlier] = []
    threshold = cfg.deviation_threshold
    for s in summaries:
        deviation = (s["total_price"] - mean) / mean
        is_outlier = False
        out_direction = "low"
        if direction == "low" and deviation < -threshold:
            is_outlier = True
            out_direction = "low"
        # high / both 预留分支:本期已在上方 fallback 到 low;不会走到这里

        if is_outlier:
            outliers.append(
                AnomalyOutlier(
                    bidder_id=s["bidder_id"],
                    total_price=s["total_price"],
                    deviation=deviation,
                    direction=out_direction,
                )
            )

    return DetectionResult(mean=mean, outliers=outliers)


__all__ = ["detect_outliers"]
