"""metadata_author Agent (pair 型) - C10 真实实现。

跨投标人字段聚类碰撞(author / last_saved_by / company 三子字段,NFKC 精确匹配)。
preflight 不变(C6 契约),仅替换 run()。
"""

from __future__ import annotations

import logging

from app.services.detect.agents._preflight_helpers import bidder_has_metadata
from app.services.detect.agents.metadata_impl import write_pair_comparison_row
from app.services.detect.agents.metadata_impl.author_detector import (
    detect_author_collisions,
)
from app.services.detect.agents.metadata_impl.config import load_author_config
from app.services.detect.agents.metadata_impl.extractor import (
    extract_bidder_metadata,
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

_DIMENSION = "metadata_author"
_ALGORITHM = "metadata_author_v1"


async def preflight(ctx: AgentContext) -> PreflightResult:
    if ctx.bidder_a is None or ctx.bidder_b is None or ctx.session is None:
        return PreflightResult("skip", "未提取到元数据")
    a_ok = await bidder_has_metadata(ctx.session, ctx.bidder_a.id, "author")
    b_ok = await bidder_has_metadata(ctx.session, ctx.bidder_b.id, "author")
    if a_ok and b_ok:
        return PreflightResult("ok")
    return PreflightResult("skip", "未提取到元数据")


def _build_summary(dim_result, is_ironclad: bool) -> str:
    hits = dim_result.get("hits", [])
    if not hits:
        return "未发现作者/修改人/公司字段碰撞"
    fields = sorted({h.get("field", "?") for h in hits})
    prefix = "[铁证] " if is_ironclad else ""
    return f"{prefix}元数据字段命中:{','.join(fields)}(共 {len(hits)} 条)"


@register_agent("metadata_author", "pair", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    cfg = load_author_config()
    if not cfg.enabled:
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": False,
            "score": None,
            "reason": "METADATA_AUTHOR_ENABLED=false",
            "participating_fields": [],
            "hits": [],
            "sub_scores": {},
            "doc_ids_a": [],
            "doc_ids_b": [],
        }
        await write_pair_comparison_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="metadata_author 子检测已禁用",
            evidence_json=evidence,
        )

    # session 为 None 时(L1 单元测试通过 mock extractor)仍走算法,write_pair_comparison_row 内部会静默跳过写入
    if ctx.bidder_a is None or ctx.bidder_b is None:
        return AgentRunResult(score=0.0, summary="上下文缺失,跳过")

    try:
        records_a = await extract_bidder_metadata(ctx.session, ctx.bidder_a.id)
        records_b = await extract_bidder_metadata(ctx.session, ctx.bidder_b.id)
        dim_result = detect_author_collisions(records_a, records_b, cfg)
    except AgentSkippedError:
        # agent-skipped-error-guard:前置 re-raise,防未来 helper 抛 AgentSkippedError 被
        # 通用 except 吞成 failed 绕过 skipped 语义(harden-async-infra H2 同型隐患)
        raise
    except Exception as e:  # noqa: BLE001 - §3 C10 兜底:整 Agent 标失败
        logger.exception("metadata_author 检测异常")
        evidence = {
            "algorithm": _ALGORITHM,
            "enabled": True,
            "error": f"{type(e).__name__}: {str(e)[:200]}",
            "score": None,
            "participating_fields": [],
            "hits": [],
            "sub_scores": {},
            "doc_ids_a": [],
            "doc_ids_b": [],
        }
        await write_pair_comparison_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary=f"metadata_author 执行失败:{type(e).__name__}",
            evidence_json=evidence,
        )

    agent_score, evidence = combine_dimension(dim_result)
    evidence["algorithm"] = _ALGORITHM
    evidence["enabled"] = True
    evidence["doc_ids_a"] = [r["bid_document_id"] for r in records_a]
    evidence["doc_ids_b"] = [r["bid_document_id"] for r in records_b]

    if dim_result["score"] is None:
        # 维度级 skip(字段全缺失)
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
