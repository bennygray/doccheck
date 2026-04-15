"""tail 子检测:跨投标人尾数组合 key 碰撞 (C11 price_impl,子检测 1)

key = (尾 N 位字符串, 整数位长);区分 ¥100 / ¥1100(尾 3 位都是 "100" 但整数位长 3 vs 4)。
hit_strength = |∩| / min(|A|, |B|)(对齐 C10 author_detector,偏重"共同占比")。
异常样本(tail_key=None)行级 skip 不假阳。
"""

from __future__ import annotations

from app.services.detect.agents.price_impl.config import TailConfig
from app.services.detect.agents.price_impl.models import PriceRow, SubDimResult


def detect_tail_collisions(
    rows_a: list[PriceRow], rows_b: list[PriceRow], cfg: TailConfig
) -> SubDimResult:
    """flatten 两侧 PriceRow,跨投标人 (tail, int_len) 组合 key 碰撞。"""
    keys_a = [r["tail_key"] for r in rows_a if r["tail_key"] is not None]
    keys_b = [r["tail_key"] for r in rows_b if r["tail_key"] is not None]
    if not keys_a or not keys_b:
        return {
            "score": None,
            "reason": "至少一侧无可比对报价行",
            "hits": [],
        }
    set_a = set(keys_a)
    set_b = set(keys_b)
    intersect = set_a & set_b
    if not intersect:
        return {"score": 0.0, "reason": None, "hits": []}
    strength = len(intersect) / min(len(set_a), len(set_b))
    strength = min(1.0, strength)

    hits: list[dict] = []
    # 按 (tail, int_len) 排序保证输出稳定
    for key in sorted(intersect):
        docs_a = [r for r in rows_a if r["tail_key"] == key]
        docs_b = [r for r in rows_b if r["tail_key"] == key]
        hits.append(
            {
                "tail": key[0],
                "int_len": key[1],
                "rows_a": [
                    (r["sheet_name"], r["row_index"], str(r["total_price_raw"]))
                    for r in docs_a
                ],
                "rows_b": [
                    (r["sheet_name"], r["row_index"], str(r["total_price_raw"]))
                    for r in docs_b
                ],
            }
        )
        if len(hits) >= cfg.max_hits:
            break
    return {"score": strength, "reason": None, "hits": hits}


__all__ = ["detect_tail_collisions"]
