"""item_list 子检测:报价表项整体相似度,两阶段对齐 (C11 price_impl,子检测 3)

阶段 1(判定同模板):两 bidder sheet_name 集合相同 + 每个同名 sheet 的行数相同。
阶段 1a(同模板):按 (sheet_name, row_index) 位置对齐,"同项同价"配对成功。
阶段 1b(非同模板):flatten + item_name_norm 精确归一精确匹配。
strength >= threshold → score=strength;否则 score=0.0。
"""

from __future__ import annotations

from app.services.detect.agents.price_impl.config import ItemListConfig
from app.services.detect.agents.price_impl.models import PriceRow, SubDimResult


def is_same_template(
    grouped_a: dict[str, list[PriceRow]],
    grouped_b: dict[str, list[PriceRow]],
) -> bool:
    """同模板判定:sheet 集合相同 + 每个同名 sheet 行数相同。"""
    if set(grouped_a.keys()) != set(grouped_b.keys()):
        return False
    for sheet in grouped_a:
        if len(grouped_a[sheet]) != len(grouped_b[sheet]):
            return False
    return True


def _detect_by_position(
    grouped_a: dict[str, list[PriceRow]],
    grouped_b: dict[str, list[PriceRow]],
    cfg: ItemListConfig,
) -> SubDimResult:
    total_pairs = 0
    matched_pairs = 0
    hits: list[dict] = []
    for sheet in sorted(grouped_a.keys()):
        rows_a_sorted = sorted(grouped_a[sheet], key=lambda r: r["row_index"])
        rows_b_sorted = sorted(grouped_b[sheet], key=lambda r: r["row_index"])
        for r_a, r_b in zip(rows_a_sorted, rows_b_sorted, strict=True):
            total_pairs += 1
            if (
                r_a["item_name_norm"] is not None
                and r_a["item_name_norm"] == r_b["item_name_norm"]
                and r_a["unit_price_raw"] is not None
                and r_a["unit_price_raw"] == r_b["unit_price_raw"]
            ):
                matched_pairs += 1
                if len(hits) < cfg.max_hits:
                    hits.append(
                        {
                            "mode": "position",
                            "sheet": sheet,
                            "row_a": r_a["row_index"],
                            "row_b": r_b["row_index"],
                            "item_name": r_a["item_name_raw"],
                        }
                    )
    if total_pairs == 0:
        return {
            "score": None,
            "reason": "阶段 1a 对齐后无有效行",
            "hits": [],
        }
    strength = matched_pairs / total_pairs
    strength = min(1.0, strength)
    score = strength if strength >= cfg.threshold else 0.0
    return {"score": score, "reason": None, "hits": hits}


def _detect_by_item_name(
    grouped_a: dict[str, list[PriceRow]],
    grouped_b: dict[str, list[PriceRow]],
    cfg: ItemListConfig,
) -> SubDimResult:
    rows_a = [r for rs in grouped_a.values() for r in rs]
    rows_b = [r for rs in grouped_b.values() for r in rs]
    names_a = {r["item_name_norm"] for r in rows_a if r["item_name_norm"]}
    names_b = {r["item_name_norm"] for r in rows_b if r["item_name_norm"]}
    if not names_a or not names_b:
        return {
            "score": None,
            "reason": "阶段 1b 至少一侧无 item_name",
            "hits": [],
        }
    intersect = names_a & names_b
    if not intersect:
        return {"score": 0.0, "reason": None, "hits": []}
    strength = len(intersect) / min(len(names_a), len(names_b))
    strength = min(1.0, strength)
    score = strength if strength >= cfg.threshold else 0.0
    hits: list[dict] = []
    for name in sorted(intersect):
        hits.append({"mode": "item_name", "item_name": name})
        if len(hits) >= cfg.max_hits:
            break
    return {"score": score, "reason": None, "hits": hits}


def detect_item_list_similarity(
    grouped_a: dict[str, list[PriceRow]],
    grouped_b: dict[str, list[PriceRow]],
    cfg: ItemListConfig,
) -> SubDimResult:
    """两阶段对齐 + 整体相似度命中。"""
    if not grouped_a or not grouped_b:
        return {
            "score": None,
            "reason": "至少一侧无报价数据",
            "hits": [],
        }
    if is_same_template(grouped_a, grouped_b):
        return _detect_by_position(grouped_a, grouped_b, cfg)
    return _detect_by_item_name(grouped_a, grouped_b, cfg)


__all__ = ["detect_item_list_similarity", "is_same_template"]
