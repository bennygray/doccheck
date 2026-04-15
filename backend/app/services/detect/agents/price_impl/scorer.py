"""4 子检测合成 Agent 级 score (C11 price_impl)

- disabled / score=None 的子检测不参与归一化
- 参与子检测的权重重归一化(不强制总权重 1)
- Agent score = (weighted / total_weight) * 100,范围 [0, 100]
- 全部 skip → score=0.0 + enabled=false + participating_subdims=[]
"""

from __future__ import annotations

from typing import Any

from app.services.detect.agents.price_impl.config import ScorerConfig
from app.services.detect.agents.price_impl.models import SubDimResult


def _shape_subdim(
    result: SubDimResult | None, enabled: bool
) -> dict[str, Any]:
    """统一子检测 evidence 结构,disabled / 缺失 result → 占位。"""
    if not enabled:
        return {
            "enabled": False,
            "score": None,
            "reason": "flag disabled",
            "hits": [],
        }
    if result is None:
        return {
            "enabled": True,
            "score": None,
            "reason": "未执行",
            "hits": [],
        }
    return {
        "enabled": True,
        "score": result.get("score"),
        "reason": result.get("reason"),
        "hits": list(result.get("hits") or []),
    }


def combine_subdims(
    results: dict[str, SubDimResult | None],
    cfg: ScorerConfig,
) -> tuple[float, dict[str, Any]]:
    """4 子检测合成。返 (agent_score_0_100, evidence_dict)。

    evidence 中 algorithm / doc_role / doc_ids_a / doc_ids_b 由 Agent run 内填充。
    """
    participating: list[str] = []
    total_weight = 0.0
    weighted = 0.0

    subdims_evidence: dict[str, dict[str, Any]] = {}
    for name in cfg.order:
        enabled = cfg.enabled.get(name, True)
        r = results.get(name)
        subdims_evidence[name] = _shape_subdim(r, enabled)

        if not enabled:
            continue
        if r is None or r.get("score") is None:
            continue
        participating.append(name)
        w = cfg.weights.get(name, 0.0)
        total_weight += w
        weighted += float(r["score"]) * w

    if not participating or total_weight <= 0:
        return (
            0.0,
            {
                "enabled": False,
                "reason": "所有子检测均 skip 或 disabled",
                "score": None,
                "participating_subdims": [],
                "subdims": subdims_evidence,
            },
        )

    score_normalized = round((weighted / total_weight) * 100.0, 2)
    score_normalized = max(0.0, min(100.0, score_normalized))
    return (
        score_normalized,
        {
            "enabled": True,
            "reason": None,
            "score": score_normalized / 100.0,
            "participating_subdims": participating,
            "subdims": subdims_evidence,
        },
    )


__all__ = ["combine_subdims"]
