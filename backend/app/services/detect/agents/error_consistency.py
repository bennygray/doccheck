"""error_consistency Agent (global 型) - C13 真实实现。

US-5.2 特殊语义:identity_info 全空 → preflight downgrade(不 skip);
run 内部仍调 L-5 LLM,但 is_iron_evidence 强制 False。

5 层兜底:
1) ENABLED=false 早返
2) preflight downgrade → ctx.downgrade=True 走降级关键词(仍调 L-5)
3) 无可抽关键词 → Agent skip 哨兵
4) L-5 LLM 失败 → 仅展示程序层 evidence 不铁证
5) L-5 返 direct_evidence=true → has_iron_evidence=true(judge.py 升铁证)

数据消费:bidder.identity_info JSONB + document_texts(body/header/footer)。
"""

from __future__ import annotations

import logging
from itertools import combinations

from app.services.detect.agents._preflight_helpers import (
    bidder_has_identity_info,
)
from app.services.detect.agents.error_impl import write_overall_analysis_row
from app.services.detect.agents.error_impl.config import (
    ErrorConsistencyConfig,
    load_config,
)
from app.services.detect.agents.error_impl.intersect_searcher import search
from app.services.detect.agents.error_impl.keyword_extractor import (
    extract_keywords,
)
from app.services.detect.agents.error_impl.llm_judge import call_l5
from app.services.detect.agents.error_impl.models import PairResult
from app.services.detect.agents.error_impl.scorer import (
    compute_agent_score,
    compute_pair_score,
)
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.registry import register_agent

logger = logging.getLogger(__name__)

_DIMENSION = "error_consistency"
_ALGORITHM = "error_consistency_v1"


async def preflight(ctx: AgentContext) -> PreflightResult:
    """≥2 bidder 必要;任一 bidder identity_info 缺 → downgrade(贴 spec 原语义)。

    保守策略:有一方数据不全就整 Agent 走降级(is_iron_evidence 强制 False)。
    降级路径仍调 L-5 LLM,但不铁证。
    """
    if len(ctx.all_bidders) < 2:
        return PreflightResult("skip", "有效投标人不足")
    any_missing = any(
        not bidder_has_identity_info(b) for b in ctx.all_bidders
    )
    if any_missing:
        return PreflightResult(
            "downgrade",
            "降级检测,建议补充标识信息后重新检测",
        )
    return PreflightResult("ok")


def _build_evidence(
    pair_results: list[PairResult],
    cfg: ErrorConsistencyConfig,
    *,
    enabled: bool,
    downgrade_mode: bool,
    skip_reason: str | None = None,
    error: str | None = None,
) -> dict:
    """组装 evidence_json。"""
    has_iron = (
        not downgrade_mode
        and any(p.get("is_iron_evidence", False) for p in pair_results)
    )
    participating: list[str] = []
    if enabled:
        participating.append("keyword_intersect")
        if any(p.get("llm_judgment") is not None for p in pair_results):
            participating.append("llm_l5")
    return {
        "algorithm_version": _ALGORITHM,
        "enabled": enabled,
        "downgrade_mode": downgrade_mode,
        "has_iron_evidence": has_iron,
        "pair_results": pair_results,
        "skip_reason": skip_reason,
        "participating_subdims": participating if not skip_reason else [],
        "llm_explanation": None,
        "error": error,
        "config": {
            "max_candidate_segments": cfg.max_candidate_segments,
            "min_keyword_len": cfg.min_keyword_len,
            "llm_max_retries": cfg.llm_max_retries,
        },
    }


def _build_summary(
    pair_results: list[PairResult],
    *,
    enabled: bool,
    downgrade_mode: bool,
    skip_reason: str | None,
    error: str | None,
) -> str:
    if not enabled:
        return "error_consistency disabled"
    if error is not None:
        return f"error_consistency 异常: {error[:80]}"
    if skip_reason:
        return f"error_consistency skip: {skip_reason}"
    iron_count = sum(
        1 for p in pair_results if p.get("is_iron_evidence", False)
    )
    hit_count = sum(
        1 for p in pair_results if p.get("suspicious_segments")
    )
    if downgrade_mode:
        prefix = "[降级检测] "
    else:
        prefix = "[铁证] " if iron_count > 0 else ""
    if hit_count == 0:
        return f"{prefix}未发现交叉污染信号"
    return (
        f"{prefix}发现 {hit_count} 对可疑交叉;铁证 {iron_count} 对"
    )


@register_agent("error_consistency", "global", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    cfg = load_config()

    # 1) ENABLED=false 早返
    if not cfg.enabled:
        evidence = _build_evidence(
            [], cfg, enabled=False, downgrade_mode=False
        )
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="error_consistency disabled",
            evidence_json=evidence,
        )

    if ctx.session is None or len(ctx.all_bidders) < 2:
        evidence = _build_evidence(
            [],
            cfg,
            enabled=True,
            downgrade_mode=ctx.downgrade,
            skip_reason="invalid_context",
        )
        # 仍写一行 OA 让维度级复核可见 skip 原因
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="error_consistency 上下文无效,跳过",
            evidence_json=evidence,
        )

    downgrade_mode = ctx.downgrade

    # 2) 抽关键词(每 bidder 独立判断 downgrade 或正常)
    bidder_keywords: dict[int, list[str]] = {}
    for b in ctx.all_bidders:
        b_downgrade = downgrade_mode or not bidder_has_identity_info(b)
        bidder_keywords[b.id] = extract_keywords(
            b, cfg, downgrade=b_downgrade
        )

    # 3) 全 bidder 都没可抽关键词 → Agent skip 哨兵
    if not any(bidder_keywords.values()):
        evidence = _build_evidence(
            [],
            cfg,
            enabled=True,
            downgrade_mode=downgrade_mode,
            skip_reason="no_extractable_keywords",
        )
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="error_consistency: 无可抽关键词",
            evidence_json=evidence,
        )

    # 4) 对每 pair 跑搜索 + L-5
    pair_results: list[PairResult] = []
    try:
        for a, b in combinations(ctx.all_bidders, 2):
            kw_a = bidder_keywords[a.id]
            kw_b = bidder_keywords[b.id]
            if not kw_a and not kw_b:
                continue
            segs, truncated, original = await search(
                ctx.session, a.id, b.id, kw_a, kw_b, cfg
            )
            judgment = None
            llm_failed = False
            llm_failure_reason: str | None = None
            if segs:
                judgment = await call_l5(
                    ctx.llm_provider, segs, a.name, b.name, cfg
                )
                if judgment is None:
                    llm_failed = True
                    llm_failure_reason = "llm_call_or_parse_failed"

            # 铁证规则:downgrade 模式强制 False;否则需 direct_evidence + is_cross_contamination
            is_iron = False
            if not downgrade_mode and judgment is not None:
                is_iron = bool(
                    judgment.get("direct_evidence")
                    and judgment.get("is_cross_contamination")
                )

            pair_score = compute_pair_score(segs, judgment)
            pair_results.append(
                PairResult(
                    bidder_a_id=a.id,
                    bidder_b_id=b.id,
                    suspicious_segments=segs,
                    truncated=truncated,
                    original_count=original,
                    llm_judgment=judgment,
                    llm_failed=llm_failed,
                    llm_failure_reason=llm_failure_reason,
                    is_iron_evidence=is_iron,
                    pair_score=pair_score,
                )
            )
    except Exception as e:  # noqa: BLE001
        logger.exception("error_consistency 检测异常")
        evidence = _build_evidence(
            pair_results,
            cfg,
            enabled=True,
            downgrade_mode=downgrade_mode,
            error=f"{type(e).__name__}: {str(e)[:200]}",
        )
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary=f"error_consistency 异常: {type(e).__name__}",
            evidence_json=evidence,
        )

    agent_score = compute_agent_score(pair_results)
    evidence = _build_evidence(
        pair_results, cfg, enabled=True, downgrade_mode=downgrade_mode
    )
    await write_overall_analysis_row(
        ctx, dimension=_DIMENSION, score=agent_score, evidence=evidence
    )
    summary = _build_summary(
        pair_results,
        enabled=True,
        downgrade_mode=downgrade_mode,
        skip_reason=None,
        error=None,
    )
    return AgentRunResult(
        score=agent_score, summary=summary, evidence_json=evidence
    )
