"""series_relation 子检测:等差/等比/比例关系 (C11 price_impl,子检测 4)

第一性原理审暴露的真信号:水平关系(bidder 之间数列关系)。
仅在同模板时跑(行对齐可靠才有方差意义)。

算法:
- ratios = [b/a ...] 的样本方差 < ratio_variance_max → 等比命中(B = A × k)
- diffs = [b-a ...] 的变异系数 CV = pstdev / |mean| < diff_cv_max → 等差命中
- 对齐样本 < min_pairs → score=None
- ratio 与 diff 任一命中 → score=1.0(强信号)
- 两者均不命中 → score=0.0
"""

from __future__ import annotations

import statistics

from app.services.detect.agents.price_impl.config import SeriesConfig
from app.services.detect.agents.price_impl.item_list_detector import (
    is_same_template,
)
from app.services.detect.agents.price_impl.models import PriceRow, SubDimResult


def detect_series_relation(
    grouped_a: dict[str, list[PriceRow]],
    grouped_b: dict[str, list[PriceRow]],
    cfg: SeriesConfig,
) -> SubDimResult:
    """对同模板对齐行序列计算等比方差与等差变异系数。"""
    if not grouped_a or not grouped_b:
        return {
            "score": None,
            "reason": "至少一侧无报价数据",
            "hits": [],
        }
    if not is_same_template(grouped_a, grouped_b):
        return {
            "score": None,
            "reason": "非同模板,series 子检测不适用",
            "hits": [],
        }

    ratios: list[float] = []
    diffs: list[float] = []
    for sheet in sorted(grouped_a.keys()):
        rows_a_sorted = sorted(grouped_a[sheet], key=lambda r: r["row_index"])
        rows_b_sorted = sorted(grouped_b[sheet], key=lambda r: r["row_index"])
        for r_a, r_b in zip(rows_a_sorted, rows_b_sorted, strict=True):
            a = r_a["total_price_float"]
            b = r_b["total_price_float"]
            if a is None or b is None or a == 0:
                continue
            ratios.append(b / a)
            diffs.append(b - a)

    pair_count = len(ratios)
    if pair_count < cfg.min_pairs:
        return {
            "score": None,
            "reason": (
                f"对齐样本不足(需 ≥ {cfg.min_pairs},实得 {pair_count})"
            ),
            "hits": [],
        }

    # 方差(用 population variance,样本固定不需估计)
    ratio_var = statistics.pvariance(ratios) if len(ratios) >= 2 else 0.0
    mean_diff = statistics.mean(diffs)
    if len(diffs) >= 2 and mean_diff != 0:
        diff_cv = statistics.pstdev(diffs) / abs(mean_diff)
    else:
        diff_cv = float("inf")

    hits: list[dict] = []
    score = 0.0

    if ratio_var < cfg.ratio_variance_max:
        k = statistics.mean(ratios)
        hits.append(
            {
                "mode": "ratio",
                "k": round(k, 6),
                "variance": round(ratio_var, 9),
                "pairs": pair_count,
            }
        )
        score = max(score, 1.0)

    if diff_cv < cfg.diff_cv_max:
        hits.append(
            {
                "mode": "diff",
                "diff": round(mean_diff, 2),
                "cv": round(diff_cv, 6),
                "pairs": pair_count,
            }
        )
        score = max(score, 1.0)

    return {"score": score, "reason": None, "hits": hits[: cfg.max_hits]}


__all__ = ["detect_series_relation"]
