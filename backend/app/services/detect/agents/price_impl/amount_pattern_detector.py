"""amount_pattern 子检测:(item_name_norm, unit_price) 对精确匹配率 (C11 price_impl,子检测 2)

直接抓"共享报价计算"真信号:同项同单价跨 bidder = 强证据。
strength = |∩| / min(|A|, |B|);< threshold → score=0.0。
异常样本(item_name_norm=None 或 unit_price_raw=None)行级 skip。
"""

from __future__ import annotations

from decimal import Decimal

from app.services.detect.agents.price_impl.config import AmountPatternConfig
from app.services.detect.agents.price_impl.models import PriceRow, SubDimResult


def _row_key(r: PriceRow) -> tuple[str, Decimal] | None:
    if r["item_name_norm"] is None or r["unit_price_raw"] is None:
        return None
    return (r["item_name_norm"], r["unit_price_raw"])


def detect_amount_pattern(
    rows_a: list[PriceRow], rows_b: list[PriceRow], cfg: AmountPatternConfig
) -> SubDimResult:
    """构造 (item_name_norm, unit_price) 对集合,跨 bidder 求交集占比。"""
    pairs_a: set[tuple[str, Decimal]] = set()
    for r in rows_a:
        k = _row_key(r)
        if k is not None:
            pairs_a.add(k)
    pairs_b: set[tuple[str, Decimal]] = set()
    for r in rows_b:
        k = _row_key(r)
        if k is not None:
            pairs_b.add(k)
    if not pairs_a or not pairs_b:
        return {
            "score": None,
            "reason": "至少一侧无 (item_name, unit_price) 有效对",
            "hits": [],
        }
    intersect = pairs_a & pairs_b
    if not intersect:
        return {"score": 0.0, "reason": None, "hits": []}
    strength = len(intersect) / min(len(pairs_a), len(pairs_b))
    strength = min(1.0, strength)
    score = strength if strength >= cfg.threshold else 0.0

    hits: list[dict] = []
    for name, price in sorted(intersect):
        hits.append(
            {"item_name": name, "unit_price": str(price)}
        )
        if len(hits) >= cfg.max_hits:
            break
    return {"score": score, "reason": None, "hits": hits}


__all__ = ["detect_amount_pattern"]
