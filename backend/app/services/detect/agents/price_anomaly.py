"""price_anomaly Agent (global 型) - C12 真实实现。

垂直关系检测:单家报价相对项目群体均值的偏离。
- sample_size < min → Agent 级 skip 哨兵(score=0.0 + participating_subdims=[])
- direction='low' + deviation < -threshold → outlier
- baseline 路径本期硬 false(follow-up)
- LLM 解释占位 null(留 C14)

不消费 bid_documents.parse_status / project_price_configs.currency。
"""

from __future__ import annotations

import logging

from app.services.detect.agents._preflight_helpers import (
    project_has_priced_bidders,
)
from app.services.detect.agents.anomaly_impl import write_overall_analysis_row
from app.services.detect.agents.anomaly_impl.config import (
    AnomalyConfig,
    load_anomaly_config,
)
from app.services.detect.agents.anomaly_impl.detector import detect_outliers
from app.services.detect.agents.anomaly_impl.extractor import (
    aggregate_bidder_totals,
)
from app.services.detect.agents.anomaly_impl.scorer import compute_score
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.registry import register_agent

logger = logging.getLogger(__name__)

_DIMENSION = "price_anomaly"
_ALGORITHM = "price_anomaly_v1"


async def preflight(ctx: AgentContext) -> PreflightResult:
    """检查项目下是否有 ≥ MIN_SAMPLE_SIZE 家 bidder 已解析报价。"""
    if ctx.session is None:
        return PreflightResult("skip", "样本数不足,无法判定异常低价")
    cfg = load_anomaly_config()
    has_enough = await project_has_priced_bidders(
        ctx.session, ctx.project_id, cfg.min_sample_size
    )
    if has_enough:
        return PreflightResult("ok")
    return PreflightResult("skip", "样本数不足,无法判定异常低价")


def _config_dict(cfg: AnomalyConfig) -> dict:
    """关键 config 回写 evidence(便于审计)。"""
    return {
        "min_sample_size": cfg.min_sample_size,
        "deviation_threshold": cfg.deviation_threshold,
        "direction": cfg.direction,
    }


def _build_summary(outliers_count: int, score: float) -> str:
    if outliers_count == 0:
        return "未发现单家异常低价"
    return (
        f"发现 {outliers_count} 家异常低价 outlier;score={score:.2f}"
    )


@register_agent("price_anomaly", "global", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    cfg = load_anomaly_config()

    # 1) ENABLED=false → 早返(不调 extractor)
    if not cfg.enabled:
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": False,
            "outliers": [],
        }
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="price_anomaly disabled",
            evidence_json=evidence,
        )

    # 2) extractor + detector 全包在 try:异常路径统一 evidence.error
    try:
        summaries = await aggregate_bidder_totals(
            ctx.session, ctx.project_id, cfg
        )
    except Exception as e:  # noqa: BLE001 - 兜底:整 Agent 标 skip + error
        logger.exception("price_anomaly extractor 异常")
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": True,
            "sample_size": 0,
            "mean": None,
            "outliers": [],
            "baseline": None,
            "llm_explanation": None,
            "participating_subdims": [],
            "error": f"{type(e).__name__}: {str(e)[:200]}",
            "config": _config_dict(cfg),
        }
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary=f"price_anomaly extractor 异常:{type(e).__name__}",
            evidence_json=evidence,
        )

    # 3) Agent 级 skip 哨兵:并发下 preflight → run 之间样本数可能变化
    if len(summaries) < cfg.min_sample_size:
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": True,
            "sample_size": len(summaries),
            "mean": None,
            "outliers": [],
            "baseline": None,
            "llm_explanation": None,
            "participating_subdims": [],
            "skip_reason": "sample_size_below_min",
            "config": _config_dict(cfg),
        }
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="样本数不足,无法判定异常低价",
            evidence_json=evidence,
        )

    # 4) 正常路径:均值偏离判定
    try:
        result = detect_outliers(summaries, cfg)
    except Exception as e:  # noqa: BLE001
        logger.exception("price_anomaly detector 异常")
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": True,
            "sample_size": len(summaries),
            "mean": None,
            "outliers": [],
            "baseline": None,
            "llm_explanation": None,
            "participating_subdims": [],
            "error": f"{type(e).__name__}: {str(e)[:200]}",
            "config": _config_dict(cfg),
        }
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary=f"price_anomaly detector 异常:{type(e).__name__}",
            evidence_json=evidence,
        )

    score = compute_score(result)
    outliers = result["outliers"]
    evidence = {
        "algorithm": _ALGORITHM,
        "enabled": True,
        "sample_size": len(summaries),
        "mean": round(result["mean"], 4),
        "outliers": [
            {
                "bidder_id": o["bidder_id"],
                "total_price": o["total_price"],
                "deviation": round(o["deviation"], 6),
                "direction": o["direction"],
            }
            for o in outliers
        ],
        "baseline": None,
        "llm_explanation": None,
        "participating_subdims": ["mean"],
        "config": _config_dict(cfg),
    }
    await write_overall_analysis_row(
        ctx, dimension=_DIMENSION, score=score, evidence=evidence
    )
    summary = _build_summary(len(outliers), score)
    return AgentRunResult(
        score=score, summary=summary, evidence_json=evidence
    )
