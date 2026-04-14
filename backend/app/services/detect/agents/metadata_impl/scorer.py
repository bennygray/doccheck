"""合成 Agent 级 score + evidence dict (C10 metadata_impl)

单维度 Agent(3 个 metadata_*):直接拿 dim_result.score × 100 作为 Agent score。
维度级 skip(dim_result.score=None):Agent score=0.0 + participating_fields=[] 哨兵。
"""

from __future__ import annotations

from typing import Any


def combine_dimension(dim_result: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """单维度合成。返 (agent_score_0_100, evidence_dict)。

    evidence 中的 algorithm / doc_ids_a / doc_ids_b / enabled 由 Agent run 内部填充。
    """
    if dim_result["score"] is None:
        return (
            0.0,
            {
                "score": None,
                "reason": dim_result.get("reason"),
                "participating_fields": [],
                "hits": list(dim_result.get("hits", [])),
                "sub_scores": dict(dim_result.get("sub_scores", {})),
            },
        )
    agent_score = round(dim_result["score"] * 100, 2)
    sub_scores = dim_result.get("sub_scores", {}) or {}
    participating: list[str] = list(sub_scores.keys())
    if not participating:
        # machine 维度(无 sub_scores);用 hits 的 field 作为 participating
        for h in dim_result.get("hits", []) or []:
            f = h.get("field") if isinstance(h, dict) else None
            if f and f not in participating:
                participating.append(f)
    return (
        agent_score,
        {
            "score": dim_result["score"],
            "reason": None,
            "participating_fields": participating,
            "hits": list(dim_result.get("hits", [])),
            "sub_scores": dict(sub_scores),
        },
    )


__all__ = ["combine_dimension"]
