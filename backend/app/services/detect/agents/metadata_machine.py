"""metadata_machine Agent (pair 型) - C10 真实实现。

(app_name, app_version, template) 三字段元组跨投标人精确碰撞。
"""

from __future__ import annotations

import logging

from app.services.detect.agents._preflight_helpers import bidder_has_metadata
from app.services.detect.agents.metadata_impl import write_pair_comparison_row
from app.services.detect.agents.metadata_impl.config import (
    load_machine_config,
)
from app.services.detect.agents.metadata_impl.extractor import (
    extract_bidder_metadata,
)
from app.services.detect.agents.metadata_impl.machine_detector import (
    detect_machine_collisions,
)
from app.services.detect.agents.metadata_impl.scorer import combine_dimension
from app.services.detect.errors import AgentSkippedError
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.registry import register_agent

logger = logging.getLogger(__name__)

_DIMENSION = "metadata_machine"
_ALGORITHM = "metadata_machine_v1"


async def preflight(ctx: AgentContext) -> PreflightResult:
    if ctx.bidder_a is None or ctx.bidder_b is None or ctx.session is None:
        return PreflightResult("skip", "未提取到元数据")
    a_ok = await bidder_has_metadata(ctx.session, ctx.bidder_a.id, "machine")
    b_ok = await bidder_has_metadata(ctx.session, ctx.bidder_b.id, "machine")
    if a_ok and b_ok:
        return PreflightResult("ok")
    return PreflightResult("skip", "未检测到定价软件输出")


def _build_summary(dim_result, is_ironclad: bool) -> str:
    hits = dim_result.get("hits", [])
    if not hits:
        return "未发现机器指纹碰撞"
    prefix = "[铁证] " if is_ironclad else ""
    return f"{prefix}机器指纹元组碰撞(共 {len(hits)} 条)"


@register_agent("metadata_machine", "pair", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    cfg = load_machine_config()
    if not cfg.enabled:
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": False,
            "score": None,
            "reason": "METADATA_MACHINE_ENABLED=false",
            "participating_fields": [],
            "hits": [],
            "doc_ids_a": [],
            "doc_ids_b": [],
        }
        await write_pair_comparison_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="metadata_machine 子检测已禁用",
            evidence_json=evidence,
        )

    if ctx.bidder_a is None or ctx.bidder_b is None:
        return AgentRunResult(score=0.0, summary="上下文缺失,跳过")

    try:
        records_a = await extract_bidder_metadata(ctx.session, ctx.bidder_a.id)
        records_b = await extract_bidder_metadata(ctx.session, ctx.bidder_b.id)
        dim_result = detect_machine_collisions(records_a, records_b, cfg)
    except AgentSkippedError:
        # agent-skipped-error-guard:前置 re-raise,防通用 except 吞 skipped 语义
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("metadata_machine 检测异常")
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": True,
            "error": f"{type(e).__name__}: {str(e)[:200]}",
            "score": None,
            "participating_fields": [],
            "hits": [],
            "doc_ids_a": [],
            "doc_ids_b": [],
        }
        await write_pair_comparison_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary=f"metadata_machine 执行失败:{type(e).__name__}",
            evidence_json=evidence,
        )

    agent_score, evidence = combine_dimension(dim_result)
    evidence["algorithm"] = _ALGORITHM
    evidence["enabled"] = True
    evidence["doc_ids_a"] = [r["bid_document_id"] for r in records_a]
    evidence["doc_ids_b"] = [r["bid_document_id"] for r in records_b]

    if dim_result["score"] is None:
        await write_pair_comparison_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary=f"元数据缺失:{dim_result['reason']}",
            evidence_json=evidence,
        )

    is_ironclad = agent_score >= cfg.ironclad_threshold
    summary = _build_summary(dim_result, is_ironclad)
    await write_pair_comparison_row(
        ctx,
        dimension=_DIMENSION,
        score=agent_score,
        evidence=evidence,
        is_ironclad=is_ironclad,
    )
    return AgentRunResult(
        score=agent_score, summary=summary, evidence_json=evidence
    )
