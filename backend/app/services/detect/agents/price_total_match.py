"""price_total_match Agent (global 型) - fix-bug-triple-and-direction-high

水平关系检测:任意两家 bidder.total_price 完全相等。

- 复用 anomaly_impl.aggregate_bidder_totals 产出 BidderPriceSummary
- 命中 → has_iron_evidence=True; score=100(由 judge 既有铁证短路升 high)
- preflight:bidder<2 或全无报价 → skip,evidence{enabled:false, reason:"数据缺失"}
- 不依赖 SystemConfig weight 配置(决策 2A 零 SystemConfig 迁移)
"""

from __future__ import annotations

import logging

from app.services.detect.agents.anomaly_impl import write_overall_analysis_row
from app.services.detect.agents.anomaly_impl.config import load_anomaly_config
from app.services.detect.agents.anomaly_impl.extractor import (
    aggregate_bidder_totals,
)
from app.services.detect.agents.price_total_match_impl.detector import (
    detect_total_matches,
)
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.errors import AgentSkippedError
from app.services.detect.registry import register_agent

logger = logging.getLogger(__name__)

_DIMENSION = "price_total_match"
_ALGORITHM = "price_total_match_v1"


async def preflight(ctx: AgentContext) -> PreflightResult:
    """≥2 家 priced bidder 是必要条件;不足直接 skip。"""
    if ctx.session is None:
        return PreflightResult("skip", "数据缺失")
    return PreflightResult("ok")


@register_agent("price_total_match", "global", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    cfg = load_anomaly_config()  # 复用既有 max_bidders 等限制
    try:
        summaries = await aggregate_bidder_totals(
            ctx.session, ctx.project_id, cfg
        )
    except AgentSkippedError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("price_total_match extractor 异常")
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": True,
            "pairs": [],
            "error": f"{type(e).__name__}: {str(e)[:200]}",
        }
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary=f"price_total_match extractor 异常:{type(e).__name__}",
            evidence_json=evidence,
        )

    if len(summaries) < 2:
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": False,
            "reason": "数据缺失",
            "pairs": [],
        }
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="数据缺失,无法判定总额相等",
            evidence_json=evidence,
        )

    pairs = detect_total_matches(summaries)
    if not pairs:
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": True,
            "pairs": [],
            "has_iron_evidence": False,
        }
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="未发现两家总额完全相等",
            evidence_json=evidence,
        )

    # 命中 → 铁证级,score=100,evidence["has_iron_evidence"]=True 让 judge 铁证短路升 high
    evidence = {
        "algorithm": _ALGORITHM,
        "enabled": True,
        "pairs": list(pairs),
        "has_iron_evidence": True,
    }
    await write_overall_analysis_row(
        ctx, dimension=_DIMENSION, score=100.0, evidence=evidence
    )
    summary = f"发现 {len(pairs)} 对投标人总额完全相等(铁证)"
    return AgentRunResult(
        score=100.0, summary=summary, evidence_json=evidence
    )
