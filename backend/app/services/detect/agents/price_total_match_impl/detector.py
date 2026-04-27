"""price_total_match 子算法:bidder 级总报价完全相等检测。"""

from __future__ import annotations

from typing import TypedDict

from app.services.detect.agents.anomaly_impl.models import BidderPriceSummary

# DECIMAL(18,2) → float 转换在 .005 内视为完全相等(金额场景 float 精度足够)
_TOTAL_EQUAL_TOLERANCE = 0.005


class TotalMatchPair(TypedDict):
    bidder_a_id: int
    bidder_a_name: str
    bidder_b_id: int
    bidder_b_name: str
    total: float


def detect_total_matches(
    summaries: list[BidderPriceSummary],
) -> list[TotalMatchPair]:
    """两两比较 bidder.total_price,完全相等 → 铁证级 pair。

    返回 pair 列表(按 bidder_a_id < bidder_b_id 去重排序),空列表表示未命中。
    """
    pairs: list[TotalMatchPair] = []
    n = len(summaries)
    for i in range(n):
        for j in range(i + 1, n):
            a = summaries[i]
            b = summaries[j]
            if abs(a["total_price"] - b["total_price"]) < _TOTAL_EQUAL_TOLERANCE:
                pairs.append(
                    TotalMatchPair(
                        bidder_a_id=a["bidder_id"],
                        bidder_a_name=a["bidder_name"],
                        bidder_b_id=b["bidder_id"],
                        bidder_b_name=b["bidder_name"],
                        total=round(a["total_price"], 2),
                    )
                )
    return pairs


__all__ = ["TotalMatchPair", "detect_total_matches"]
