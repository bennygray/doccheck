"""price_consistency Agent (pair 型) - C11 真实实现。

4 子检测合成:tail / amount_pattern / item_list / series_relation。
所有数据从 PriceItem 表读取,不消费 DocumentSheet,不读 currency / tax_inclusive。
preflight 不变(C6 契约),仅替换 run()。
"""

from __future__ import annotations

import logging

from app.services.detect import baseline_resolver
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
from app.services.detect.agents.price_impl.models import PriceRow
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


def _filter_grouped_by_baseline(
    grouped: dict[str, list[PriceRow]],
    baseline_set: set[str],
) -> tuple[dict[str, list[PriceRow]], int]:
    """detect-tender-baseline §5:从 grouped 中剔除 boq_baseline_hash ∈ baseline 的行。

    返 (filtered_grouped, excluded_count)。
    - boq_baseline_hash 为 NULL 的行**不**被剔除(老数据 / 不完整行兜底,fail-soft)
    - 全空 set 时直接返原 grouped + 0(短路,零开销)
    """
    if not baseline_set:
        return grouped, 0
    filtered: dict[str, list[PriceRow]] = {}
    excluded = 0
    for sheet, rows in grouped.items():
        kept = []
        for r in rows:
            h = r.get("boq_baseline_hash")
            if h is not None and h in baseline_set:
                excluded += 1
                continue
            kept.append(r)
        if kept:
            filtered[sheet] = kept
    return filtered, excluded


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
            # detect-tender-baseline §5:即使全部禁用,evidence schema 也带 baseline 字段
            "baseline_source": "none",
            "warnings": [],
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

    # detect-tender-baseline §5:加载 BOQ 项级 baseline hash 集合(D5 仅 L1 tender 路径,
    # L2 共识不适用 BOQ — 招标方下发同一份工程量清单合法,共识阈值会把多家应标方
    # 全部误剔成"模板"变零分);fail-soft:任何异常返空 baseline,不阻 detector
    try:
        baseline_segs = await baseline_resolver.get_excluded_segment_hashes_with_source(
            ctx.session, ctx.project_id, "price_consistency"
        )
        baseline_boq_hashes = set(baseline_segs.hash_to_source.keys())
        baseline_source = baseline_segs.baseline_source
        baseline_warnings = list(baseline_segs.warnings)
    except AgentSkippedError:
        # agent-skipped-error-guard:前置 re-raise,防 helper 抛 AgentSkippedError 被
        # 通用 except 吞成 failed 绕过 skipped 语义(harden-async-infra H2 同型)
        raise
    except Exception as exc:  # noqa: BLE001 - baseline 失败 fail-soft 不阻 detector
        logger.error(
            "price_consistency: baseline_resolver failed project=%s err=%s",
            ctx.project_id,
            exc,
        )
        baseline_boq_hashes = set()
        baseline_source = "none"
        baseline_warnings = []

    try:
        grouped_a_raw = await extract_bidder_prices(
            ctx.session, ctx.bidder_a.id, cfg
        )
        grouped_b_raw = await extract_bidder_prices(
            ctx.session, ctx.bidder_b.id, cfg
        )
        # detect-tender-baseline §5:在 detector 链前剔除 baseline 命中行
        # (零侵入 4 个子检测,所有子检测在过滤后的 grouped/rows 上跑)
        grouped_a, excluded_a = _filter_grouped_by_baseline(
            grouped_a_raw, baseline_boq_hashes
        )
        grouped_b, excluded_b = _filter_grouped_by_baseline(
            grouped_b_raw, baseline_boq_hashes
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
            # detect-tender-baseline §5:错误路径 evidence 也带 baseline 字段
            "baseline_source": baseline_source,
            "warnings": baseline_warnings,
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
    # detect-tender-baseline §5:PC 顶级 baseline_source / warnings + 过滤计数
    # (filter 已在 detector 链前应用,baseline-命中行不参与 score 计算 → 自然不顶 ironclad)
    evidence["baseline_source"] = baseline_source
    evidence["warnings"] = baseline_warnings
    evidence["baseline_excluded_row_count"] = {
        "bidder_a": excluded_a,
        "bidder_b": excluded_b,
    }

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
