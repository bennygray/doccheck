"""price_consistency Agent (pair 型) - C11 真实实现。

4 子检测合成:tail / amount_pattern / item_list / series_relation。
所有数据从 PriceItem 表读取,不消费 DocumentSheet,不读 currency / tax_inclusive。
preflight 不变(C6 契约),仅替换 run()。
"""

from __future__ import annotations

import logging

from app.services.detect.agents._preflight_helpers import bidder_has_priced
from app.services.detect.agents.price_impl import write_pair_comparison_row
from app.services.detect.agents.price_impl.amount_pattern_detector import (
    detect_amount_pattern,
)
from app.services.detect.agents.price_impl.config import load_price_config
from app.services.detect.agents.price_impl.extractor import (
    extract_bidder_prices,
    flatten_rows,
)
from app.services.detect.agents.price_impl.item_list_detector import (
    detect_item_list_similarity,
)
from app.services.detect.agents.price_impl.scorer import combine_subdims
from app.services.detect.agents.price_impl.series_relation_detector import (
    detect_series_relation,
)
from app.services.detect.agents.price_impl.tail_detector import (
    detect_tail_collisions,
)
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.errors import AgentSkippedError
from app.services.detect.registry import register_agent

logger = logging.getLogger(__name__)

_DIMENSION = "price_consistency"
_ALGORITHM = "price_consistency_v1"
_DOC_ROLE = "priced"


async def preflight(ctx: AgentContext) -> PreflightResult:
    if ctx.bidder_a is None or ctx.bidder_b is None or ctx.session is None:
        return PreflightResult("skip", "未找到报价表")
    a_ok = await bidder_has_priced(ctx.session, ctx.bidder_a.id)
    b_ok = await bidder_has_priced(ctx.session, ctx.bidder_b.id)
    if a_ok and b_ok:
        return PreflightResult("ok")
    return PreflightResult("skip", "未找到报价表")


def _build_summary(
    evidence: dict, agent_score: float, is_ironclad: bool
) -> str:
    if not evidence.get("enabled"):
        return "所有子检测均 skip"
    participating = evidence.get("participating_subdims", [])
    subdims = evidence.get("subdims", {})
    hit_names = [
        n for n in participating if (subdims.get(n, {}).get("score") or 0) > 0
    ]
    if not hit_names:
        return f"未发现报价一致信号(参与子检测 {len(participating)} 个)"
    prefix = "[铁证] " if is_ironclad else ""
    return (
        f"{prefix}报价一致命中:{','.join(hit_names)};score={agent_score:.2f}"
    )


def _doc_ids_from_grouped(grouped: dict) -> list[int]:
    """从分组结构提取所有 price_item_id(供 evidence 给前端定位)。"""
    return sorted(
        {
            r["price_item_id"]
            for rows in grouped.values()
            for r in rows
        }
    )


@register_agent("price_consistency", "pair", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    cfg = load_price_config()

    # 全部 4 flag 都关闭 → 整 Agent 早返
    if not any(cfg.scorer.enabled.values()):
        evidence = {
            "algorithm": _ALGORITHM,
            "doc_role": _DOC_ROLE,
            "enabled": False,
            "score": None,
            "reason": "PRICE_CONSISTENCY 4 子检测全部禁用",
            "participating_subdims": [],
            "subdims": {
                name: {
                    "enabled": False,
                    "score": None,
                    "reason": "flag disabled",
                    "hits": [],
                }
                for name in cfg.scorer.order
            },
            "doc_ids_a": [],
            "doc_ids_b": [],
        }
        await write_pair_comparison_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary="price_consistency 全部子检测已禁用",
            evidence_json=evidence,
        )

    # session 为 None 时(L1 单元测试 mock extractor)仍走算法,write_pair_comparison_row 内部静默跳过
    if ctx.bidder_a is None or ctx.bidder_b is None:
        return AgentRunResult(score=0.0, summary="上下文缺失,跳过")

    try:
        grouped_a = await extract_bidder_prices(
            ctx.session, ctx.bidder_a.id, cfg
        )
        grouped_b = await extract_bidder_prices(
            ctx.session, ctx.bidder_b.id, cfg
        )
        rows_a = flatten_rows(grouped_a)
        rows_b = flatten_rows(grouped_b)

        results: dict = {}
        if cfg.scorer.enabled["tail"]:
            results["tail"] = detect_tail_collisions(rows_a, rows_b, cfg.tail)
        else:
            results["tail"] = None

        if cfg.scorer.enabled["amount_pattern"]:
            results["amount_pattern"] = detect_amount_pattern(
                rows_a, rows_b, cfg.amount_pattern
            )
        else:
            results["amount_pattern"] = None

        if cfg.scorer.enabled["item_list"]:
            results["item_list"] = detect_item_list_similarity(
                grouped_a, grouped_b, cfg.item_list
            )
        else:
            results["item_list"] = None

        if cfg.scorer.enabled["series"]:
            results["series"] = detect_series_relation(
                grouped_a, grouped_b, cfg.series
            )
        else:
            results["series"] = None
    except AgentSkippedError:
        # agent-skipped-error-guard:前置 re-raise,防通用 except 吞 skipped 语义
        raise
    except Exception as e:  # noqa: BLE001 - §3 C11 兜底:整 Agent 标失败
        logger.exception("price_consistency 检测异常")
        evidence = {
            "algorithm": _ALGORITHM,
            "doc_role": _DOC_ROLE,
            "enabled": True,
            "error": f"{type(e).__name__}: {str(e)[:200]}",
            "score": None,
            "participating_subdims": [],
            "subdims": {
                name: {
                    "enabled": cfg.scorer.enabled.get(name, True),
                    "score": None,
                    "reason": "执行异常",
                    "hits": [],
                }
                for name in cfg.scorer.order
            },
            "doc_ids_a": [],
            "doc_ids_b": [],
        }
        await write_pair_comparison_row(
            ctx, dimension=_DIMENSION, score=0.0, evidence=evidence
        )
        return AgentRunResult(
            score=0.0,
            summary=f"price_consistency 执行失败:{type(e).__name__}",
            evidence_json=evidence,
        )

    agent_score, evidence = combine_subdims(results, cfg.scorer)
    evidence["algorithm"] = _ALGORITHM
    evidence["doc_role"] = _DOC_ROLE
    evidence["doc_ids_a"] = _doc_ids_from_grouped(grouped_a)
    evidence["doc_ids_b"] = _doc_ids_from_grouped(grouped_b)

    is_ironclad = (
        evidence.get("enabled", False)
        and agent_score >= cfg.scorer.ironclad_threshold
    )
    summary = _build_summary(evidence, agent_score, is_ironclad)
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
