"""style Agent (global 型) - C13 真实实现。

L-8 两阶段全 LLM 算法(贴 spec §F-DA-06 "LLM 独有维度,程序不参与"):
- Stage1: 每 bidder 1 次调用 → 风格特征摘要
- Stage2: 全局 1 次调用 → 风格高度一致 bidder 组合
- >20 bidder 自动分组(每组 ≤20,本期不跨组比)

任一阶段 LLM 失败 → Agent skip 哨兵(spec 明确"程序不参与",不走程序兜底)。

4 层兜底:
1) ENABLED=false 早返
2) preflight skip(< 2 bidder 有 technical 文档)
3) Stage1 任一 bidder 失败 → Agent skip 哨兵
4) Stage2 失败 → Agent skip 哨兵
"""

from __future__ import annotations

import logging
import math

from app.services.detect.agents._preflight_helpers import bidder_has_role
from app.services.detect.agents.style_impl import write_overall_analysis_row
from app.services.detect.agents.style_impl.config import (
    StyleConfig,
    load_config,
)
from app.services.detect.agents.style_impl.llm_client import (
    call_l8_stage1,
    call_l8_stage2,
)
from app.services.detect.agents.style_impl.models import StyleFeatureBrief
from app.services.detect.agents.style_impl.sampler import sample
from app.services.detect.errors import AgentSkippedError
from app.services.detect.agents.style_impl.scorer import (
    LIMITATION_NOTE,
    compute_score,
)
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.registry import register_agent

logger = logging.getLogger(__name__)

_DIMENSION = "style"
_ALGORITHM = "style_v1"
_TECHNICAL_ROLE = "technical"


async def preflight(ctx: AgentContext) -> PreflightResult:
    if len(ctx.all_bidders) < 2 or ctx.session is None:
        return PreflightResult("skip", "缺少可对比文档")
    count_with_role = 0
    for b in ctx.all_bidders:
        if await bidder_has_role(ctx.session, b.id, _TECHNICAL_ROLE):
            count_with_role += 1
            if count_with_role >= 2:
                return PreflightResult("ok")
    return PreflightResult("skip", "缺少可对比文档")


def _build_evidence(
    cfg: StyleConfig,
    *,
    enabled: bool,
    style_features: dict[str, StyleFeatureBrief] | None = None,
    global_comparison: dict | None = None,
    grouping_strategy: str = "single",
    group_count: int = 1,
    insufficient_sample_bidders: list[int] | None = None,
    skip_reason: str | None = None,
    error: str | None = None,
) -> dict:
    participating: list[str] = []
    if enabled and skip_reason is None and error is None:
        if style_features:
            participating.append("llm_l8_stage1")
        if global_comparison is not None:
            participating.append("llm_l8_stage2")
    return {
        "algorithm_version": _ALGORITHM,
        "enabled": enabled,
        "grouping_strategy": grouping_strategy,
        "group_count": group_count,
        "style_features_per_bidder": style_features or {},
        "global_comparison": global_comparison
        if global_comparison is not None
        else {"consistent_groups": []},
        "limitation_note": LIMITATION_NOTE,
        "insufficient_sample_bidders": insufficient_sample_bidders or [],
        "llm_explanation": None,
        "skip_reason": skip_reason,
        "participating_subdims": participating if not skip_reason else [],
        "error": error,
        "config": {
            "group_threshold": cfg.group_threshold,
            "sample_per_bidder": cfg.sample_per_bidder,
            "tfidf_filter_ratio": cfg.tfidf_filter_ratio,
        },
    }


def _build_summary(
    *,
    enabled: bool,
    skip_reason: str | None,
    error: str | None,
    consistent_groups_count: int,
) -> str:
    if not enabled:
        return "style disabled"
    if error:
        return f"style 异常: {error[:80]}"
    if skip_reason:
        return f"语言风格分析不可用: {skip_reason}"
    if consistent_groups_count == 0:
        return "未发现风格一致的投标人组合"
    return f"发现 {consistent_groups_count} 组风格高度一致投标人"


def _split_groups(bidder_ids: list[int], threshold: int) -> list[list[int]]:
    """按 bidder_id 升序切片为多组,每组 ≤ threshold。"""
    sorted_ids = sorted(bidder_ids)
    if len(sorted_ids) <= threshold:
        return [sorted_ids]
    n_groups = math.ceil(len(sorted_ids) / threshold)
    groups: list[list[int]] = []
    for i in range(n_groups):
        groups.append(sorted_ids[i * threshold : (i + 1) * threshold])
    return groups


@register_agent("style", "global", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    cfg = load_config()

    # 1) ENABLED=false 早返
    if not cfg.enabled:
        evidence = _build_evidence(cfg, enabled=False)
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="style disabled",
            evidence_json=evidence,
        )

    if ctx.session is None or len(ctx.all_bidders) < 2:
        evidence = _build_evidence(
            cfg, enabled=True, skip_reason="invalid_context"
        )
        # 仍写一行 OA 让前端可见 skip 原因(贴"enabled=false 早返也写" 语义)
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="style 上下文无效,跳过",
            evidence_json=evidence,
        )

    # 分组
    bidder_ids = [b.id for b in ctx.all_bidders]
    groups = _split_groups(bidder_ids, cfg.group_threshold)
    grouping_strategy = "grouped" if len(groups) > 1 else "single"

    bidder_id_to_obj = {b.id: b for b in ctx.all_bidders}

    # 累加结果(跨组合并)
    all_briefs: dict[str, StyleFeatureBrief] = {}
    insufficient_bidders: list[int] = []
    all_consistent_groups: list[dict] = []

    try:
        for group_bids in groups:
            # Stage1: 每 bidder 抽样 + LLM
            briefs_in_group: dict[int, StyleFeatureBrief] = {}
            for bid in group_bids:
                paragraphs, insufficient = await sample(
                    ctx.session, bid, cfg
                )
                if insufficient:
                    insufficient_bidders.append(bid)
                if not paragraphs:
                    # 无段落送 LLM 没意义,跳过
                    continue
                brief = await call_l8_stage1(
                    ctx.llm_provider, bid, paragraphs, cfg
                )
                if brief is None:
                    # Stage1 失败 → Agent skip
                    evidence = _build_evidence(
                        cfg,
                        enabled=True,
                        skip_reason=f"L-8 Stage1 LLM 调用失败 (bidder={bid})",
                    )
                    await write_overall_analysis_row(
                        ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
                    )
                    return AgentRunResult(
                        score=0.0,
                        summary=_build_summary(
                            enabled=True,
                            skip_reason="L-8 Stage1 LLM 调用失败",
                            error=None,
                            consistent_groups_count=0,
                        ),
                        evidence_json=evidence,
                    )
                if insufficient:
                    brief["low_confidence"] = True
                brief["bidder_id"] = bid
                briefs_in_group[bid] = brief
                all_briefs[str(bid)] = brief

            # 该组 Stage1 全部失败/无段落 → 跳过 Stage2
            if len(briefs_in_group) < 2:
                continue

            # Stage2: 该组全局比较
            comparison = await call_l8_stage2(
                ctx.llm_provider, briefs_in_group, cfg
            )
            if comparison is None:
                evidence = _build_evidence(
                    cfg,
                    enabled=True,
                    skip_reason="L-8 Stage2 LLM 调用失败",
                )
                await write_overall_analysis_row(
                    ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
                )
                return AgentRunResult(
                    score=0.0,
                    summary=_build_summary(
                        enabled=True,
                        skip_reason="L-8 Stage2 LLM 调用失败",
                        error=None,
                        consistent_groups_count=0,
                    ),
                    evidence_json=evidence,
                )
            all_consistent_groups.extend(
                comparison.get("consistent_groups", [])
            )
    except AgentSkippedError as skip_exc:
        # harden-async-infra N7 + reviewer H2:LLM 所有重试耗尽 → AgentSkippedError
        # 逸出,交给 engine._execute_agent_task 走 _mark_skipped 路径。
        #
        # MUST 在 except Exception 之前。**且必须先写 OA stub**(score=0 + skip_reason
        # in evidence),保持与 pre-N7 降级路径的"UI/report 页有 style 维度条目"行为
        # 一致,避免 ReportPage 按 OA 枚举维度时 style 整行消失 — 这是 reviewer H2
        # 点出的回归风险(旧路径 `if brief is None: return AgentRunResult(score=0)`
        # 之前一直在写 OA 行)。
        evidence = _build_evidence(
            cfg, enabled=True, skip_reason=f"L-8 LLM 失败: {skip_exc}"
        )
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("style 异常")
        evidence = _build_evidence(
            cfg, enabled=True, error=f"{type(e).__name__}: {str(e)[:200]}"
        )
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary=f"style 异常: {type(e).__name__}",
            evidence_json=evidence,
        )

    # 用 bidder_id_to_obj 静默标记(避免 unused 警告)
    _ = bidder_id_to_obj

    global_comparison = {"consistent_groups": all_consistent_groups}
    score = compute_score(global_comparison)  # type: ignore[arg-type]
    evidence = _build_evidence(
        cfg,
        enabled=True,
        style_features=all_briefs,
        global_comparison=global_comparison,
        grouping_strategy=grouping_strategy,
        group_count=len(groups),
        insufficient_sample_bidders=insufficient_bidders,
    )
    await write_overall_analysis_row(
        ctx, dimension=_DIMENSION, score=score, evidence=evidence
    )
    summary = _build_summary(
        enabled=True,
        skip_reason=None,
        error=None,
        consistent_groups_count=len(all_consistent_groups),
    )
    return AgentRunResult(
        score=score, summary=summary, evidence_json=evidence
    )
