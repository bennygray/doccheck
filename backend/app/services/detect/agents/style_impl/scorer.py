"""style 评分公式 (C13 占位)

公式:min(100, len(consistent_groups) * 30 + max(group.consistency_score) * 50)
- 一致组数加分(每组 30)
- 最高一致度加分(0~1 → 0~50)
- 上限 100

evidence.limitation_note 由调用方固定填入(spec §F-DA-06 强制要求)。
"""

from __future__ import annotations

from app.services.detect.agents.style_impl.models import GlobalComparison


LIMITATION_NOTE = (
    "风格一致可能源于同一主体操控,也可能源于委托同一代写服务,"
    "需结合其他维度综合判断"
)


def compute_score(comparison: GlobalComparison | None) -> float:
    if comparison is None:
        return 0.0
    groups = comparison.get("consistent_groups", [])
    if not groups:
        return 0.0
    count_score = len(groups) * 30.0
    max_consistency = max(
        float(g.get("consistency_score", 0.0)) for g in groups
    )
    return min(100.0, count_score + max_consistency * 50.0)


__all__ = ["compute_score", "LIMITATION_NOTE"]
