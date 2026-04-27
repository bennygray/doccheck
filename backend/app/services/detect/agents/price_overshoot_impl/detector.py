"""price_overshoot 子算法:任一 bidder.total_price > max_price 检测。"""

from __future__ import annotations

from typing import TypedDict

from app.services.detect.agents.anomaly_impl.models import BidderPriceSummary


class OvershootBidder(TypedDict):
    bidder_id: int
    bidder_name: str
    total: float
    ratio: float  # (total - max_price) / max_price


def detect_overshoot(
    summaries: list[BidderPriceSummary],
    max_price: float,
) -> list[OvershootBidder]:
    """任一 bidder.total_price > max_price → 收集进 overshoot_bidders。

    严格大于 max_price(等于不算超限)。max_price ≤ 0 由调用方 preflight 拦,
    本函数假定输入合法。
    """
    overshoot: list[OvershootBidder] = []
    for s in summaries:
        if s["total_price"] > max_price:
            ratio = (s["total_price"] - max_price) / max_price
            overshoot.append(
                OvershootBidder(
                    bidder_id=s["bidder_id"],
                    bidder_name=s["bidder_name"],
                    total=round(s["total_price"], 2),
                    ratio=round(ratio, 4),
                )
            )
    return overshoot


__all__ = ["OvershootBidder", "detect_overshoot"]
