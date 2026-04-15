"""error_consistency 评分公式 (C13 占位)

pair 级公式(每 pair 一个 score):
- 基础分:hit_segment_count * 20
- 直接证据加分:direct_evidence=true → +40
- LLM 置信度加分:is_cross_contamination=true → +confidence*20
- 上限 100

整 Agent score:取 max(pair_score)。
"""

from __future__ import annotations

from app.services.detect.agents.error_impl.models import (
    LLMJudgment,
    PairResult,
    SuspiciousSegment,
)


def compute_pair_score(
    hits: list[SuspiciousSegment],
    judgment: LLMJudgment | None,
) -> float:
    base = min(100.0, len(hits) * 20.0)
    if judgment is None:
        # LLM 失败 / 跳过 → 仅程序部分
        return base
    score = base
    if judgment.get("is_cross_contamination"):
        score += float(judgment.get("confidence", 0.0)) * 20.0
    if judgment.get("direct_evidence"):
        score += 40.0
    return min(100.0, score)


def compute_agent_score(pair_results: list[PairResult]) -> float:
    """整 Agent score = max(pair_score),空返 0.0。"""
    if not pair_results:
        return 0.0
    return max(float(p.get("pair_score", 0.0)) for p in pair_results)


__all__ = ["compute_pair_score", "compute_agent_score"]
