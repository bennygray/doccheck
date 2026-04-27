"""price_overshoot Agent (global 型) - fix-bug-triple-and-direction-high

合规底线检测:任一 bidder.total_price > Project.max_price。

- 决策 1A:超限一律 ironclad(简单先做,follow-up 可分级阈值化)
- preflight:max_price=NULL 或 ≤0 → skip,evidence{enabled:false, reason:"未设限价"}
- 不依赖 SystemConfig weight 配置(决策 2A 零迁移)
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.models.project import Project
from app.services.detect.agents.anomaly_impl import write_overall_analysis_row
from app.services.detect.agents.anomaly_impl.config import load_anomaly_config
from app.services.detect.agents.anomaly_impl.extractor import (
    aggregate_bidder_totals,
)
from app.services.detect.agents.price_overshoot_impl.detector import (
    detect_overshoot,
)
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.errors import AgentSkippedError
from app.services.detect.registry import register_agent

logger = logging.getLogger(__name__)

_DIMENSION = "price_overshoot"
_ALGORITHM = "price_overshoot_v1"


async def _load_max_price(ctx: AgentContext) -> float | None:
    """加载 project.max_price → float;NULL/缺失返 None。"""
    if ctx.session is None:
        return None
    project = await ctx.session.get(Project, ctx.project_id)
    if project is None or project.max_price is None:
        return None
    try:
        return float(project.max_price)
    except (TypeError, ValueError):
        return None


async def preflight(ctx: AgentContext) -> PreflightResult:
    """max_price=NULL or ≤0 → skip。"""
    max_price = await _load_max_price(ctx)
    if max_price is None or max_price <= 0:
        return PreflightResult("skip", "未设限价")
    return PreflightResult("ok")


@register_agent("price_overshoot", "global", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    cfg = load_anomaly_config()  # 复用既有 max_bidders 等限制
    max_price = await _load_max_price(ctx)
    if max_price is None or max_price <= 0:
        # preflight 应该已拦,这里是并发竞态兜底
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": False,
            "reason": "未设限价",
            "overshoot_bidders": [],
        }
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="未设限价,跳过超限检测",
            evidence_json=evidence,
        )

    try:
        summaries = await aggregate_bidder_totals(
            ctx.session, ctx.project_id, cfg
        )
    except AgentSkippedError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("price_overshoot extractor 异常")
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": True,
            "max_price": max_price,
            "overshoot_bidders": [],
            "error": f"{type(e).__name__}: {str(e)[:200]}",
        }
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary=f"price_overshoot extractor 异常:{type(e).__name__}",
            evidence_json=evidence,
        )

    overshoot = detect_overshoot(summaries, max_price)
    if not overshoot:
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": True,
            "max_price": max_price,
            "overshoot_bidders": [],
            "has_iron_evidence": False,
        }
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="未发现超限投标",
            evidence_json=evidence,
        )

    # 命中 → 铁证级,score=100,evidence["has_iron_evidence"]=True 让 judge 铁证短路升 high
    evidence = {
        "algorithm": _ALGORITHM,
        "enabled": True,
        "max_price": max_price,
        "overshoot_bidders": list(overshoot),
        "has_iron_evidence": True,
    }
    await write_overall_analysis_row(
        ctx, dimension=_DIMENSION, score=100.0, evidence=evidence
    )
    summary = f"发现 {len(overshoot)} 家投标超过最高限价(铁证)"
    return AgentRunResult(
        score=100.0, summary=summary, evidence_json=evidence
    )
