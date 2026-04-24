"""image_reuse Agent (global 型) - C13 真实实现。

MD5 + pHash 双路检测:
- MD5 字节级精确命中 → hit_strength=1.0(强信号)
- pHash Hamming distance ≤ threshold → hit_strength=1-d/64(视觉相似)
- 小图(< MIN_WIDTH/HEIGHT)SQL 层过滤
- MAX_PAIRS 上限按 hit_strength 倒序截断

不引 L-7 LLM 非通用图判断;is_iron_evidence 始终 False(本期不升铁证)。
evidence 占位 llm_non_generic_judgment=null 留 follow-up。

3 层兜底:
1) ENABLED=false 早返
2) preflight skip(< 2 bidder 有图)
3) 小图过滤后 0 张可比 → Agent skip 哨兵
"""

from __future__ import annotations

import logging

from app.services.detect.agents._preflight_helpers import bidder_has_images
from app.services.detect.agents.image_impl import write_overall_analysis_row
from app.services.detect.agents.image_impl.config import (
    ImageReuseConfig,
    load_config,
)
from app.services.detect.agents.image_impl.hamming_comparator import compare
from app.services.detect.agents.image_impl.scorer import compute_score
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.errors import AgentSkippedError
from app.services.detect.registry import register_agent

logger = logging.getLogger(__name__)

_DIMENSION = "image_reuse"
_ALGORITHM = "image_reuse_v1"


async def preflight(ctx: AgentContext) -> PreflightResult:
    if len(ctx.all_bidders) < 2 or ctx.session is None:
        return PreflightResult("skip", "未提取到图片")
    count = 0
    for b in ctx.all_bidders:
        if await bidder_has_images(ctx.session, b.id):
            count += 1
            if count >= 2:
                return PreflightResult("ok")
    return PreflightResult("skip", "未提取到图片")


def _build_evidence(
    md5_matches: list,
    phash_matches: list,
    cfg: ImageReuseConfig,
    *,
    enabled: bool,
    truncated: bool = False,
    original_count: int = 0,
    skip_reason: str | None = None,
    error: str | None = None,
) -> dict:
    participating: list[str] = []
    if enabled and skip_reason is None and error is None:
        if md5_matches:
            participating.append("md5_exact")
        if phash_matches:
            participating.append("phash_hamming")
        if not participating:
            # 跑了但无命中,标两个 subdim 已参与
            participating = ["md5_exact", "phash_hamming"]
    return {
        "algorithm_version": _ALGORITHM,
        "enabled": enabled,
        "md5_matches": md5_matches,
        "phash_matches": phash_matches,
        "truncated": truncated,
        "original_count": original_count,
        "llm_non_generic_judgment": None,  # follow-up: L-7 升铁证
        "llm_explanation": None,
        "skip_reason": skip_reason,
        "participating_subdims": participating if not skip_reason else [],
        "error": error,
        "config": {
            "phash_distance_threshold": cfg.phash_distance_threshold,
            "min_width": cfg.min_width,
            "min_height": cfg.min_height,
            "max_pairs": cfg.max_pairs,
        },
    }


def _build_summary(
    md5_matches: list,
    phash_matches: list,
    *,
    enabled: bool,
    skip_reason: str | None,
    error: str | None,
) -> str:
    if not enabled:
        return "image_reuse disabled"
    if error:
        return f"image_reuse 异常: {error[:80]}"
    if skip_reason:
        return f"image_reuse skip: {skip_reason}"
    md5_n = len(md5_matches)
    phash_n = len(phash_matches)
    if md5_n == 0 and phash_n == 0:
        return "未发现图片复用信号"
    return f"图片复用命中:byte_match={md5_n}, visual_similar={phash_n}"


@register_agent("image_reuse", "global", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    cfg = load_config()

    # 1) ENABLED=false 早返
    if not cfg.enabled:
        evidence = _build_evidence([], [], cfg, enabled=False)
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="image_reuse disabled",
            evidence_json=evidence,
        )

    if ctx.session is None:
        evidence = _build_evidence(
            [], [], cfg, enabled=True, skip_reason="invalid_context"
        )
        # session=None 时 write_overall_analysis_row 内部静默跳过,
        # 但仍调用以保持代码一致性
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="image_reuse 上下文无效,跳过",
            evidence_json=evidence,
        )

    # 2) 比较
    try:
        result = await compare(ctx.session, ctx.project_id, cfg)
    except AgentSkippedError:
        # agent-skipped-error-guard:前置 re-raise,防通用 except 吞 skipped 语义
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("image_reuse 比较异常")
        evidence = _build_evidence(
            [],
            [],
            cfg,
            enabled=True,
            error=f"{type(e).__name__}: {str(e)[:200]}",
        )
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary=f"image_reuse 异常: {type(e).__name__}",
            evidence_json=evidence,
        )

    md5_matches = result.get("md5_matches", [])
    phash_matches = result.get("phash_matches", [])
    truncated = result.get("truncated", False)
    original_count = result.get("original_count", 0)

    # 3) 0 命中 + 0 候选 → 小图过滤后无可比图 skip 哨兵
    if not md5_matches and not phash_matches and original_count == 0:
        evidence = _build_evidence(
            [],
            [],
            cfg,
            enabled=True,
            skip_reason="no_comparable_images_after_size_filter",
        )
        await write_overall_analysis_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="image_reuse: 小图过滤后无可比图",
            evidence_json=evidence,
        )

    score = compute_score(result)
    evidence = _build_evidence(
        md5_matches,
        phash_matches,
        cfg,
        enabled=True,
        truncated=truncated,
        original_count=original_count,
    )
    await write_overall_analysis_row(
        ctx, dimension=_DIMENSION, score=score, evidence=evidence
    )
    summary = _build_summary(
        md5_matches, phash_matches, enabled=True, skip_reason=None, error=None
    )
    return AgentRunResult(
        score=score, summary=summary, evidence_json=evidence
    )
