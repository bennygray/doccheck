"""综合研判 (C6 骨架 + C14 L-9 LLM 接入)

C6: requirements §F-RP-01 10 维度加权求和 → total_score + risk_level;
    铁证命中强制至少 high;llm_conclusion 占位留空。
C12: 新增 price_anomaly global 维度(权重 0.07,从 price_consistency / image_reuse 释放)。
C13: judge.compute_report 扩读 OverallAnalysis.evidence_json["has_iron_evidence"] 支持 global 型铁证升级。
C14: 在 compute_report 之后插入 L-9 LLM 综合研判层(预聚合摘要 → LLM → 可升不可降 clamp →
     失败模板兜底)。compute_report 纯函数签名契约不变。
DEF-OA: judge 阶段为 7 个 pair 维度补写 OA 聚合行,使 overall_analyses 每版本恰好 11 行,
     维度级复核 API 对所有维度可用。
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_metadata import DocumentMetadata
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.services.detect import baseline_resolver, judge_llm
from app.services.detect.template_cluster import (
    TEMPLATE_FILE_ROLES,
    Adjustment,
    _apply_template_adjustments,
    _detect_template_cluster,
)
from app.services.llm.base import LLMProvider
from app.services.parser.pipeline.progress_broker import progress_broker

logger = logging.getLogger(__name__)


# 13 维度权重,合计 1.00。
# fix-bug-triple-and-direction-high I-Weight-1:多维度均摊释放 0.06 给 2 个新 global Agent
# (price_total_match / price_overshoot 各 0.03),避免单一维度权重砍幅过大。
# 释放来源:error_consistency 0.12→0.10(-0.02) / style 0.08→0.07(-0.01) /
# image_reuse 0.05→0.02(-0.03)。新 2 维实际不依赖权重生效(由 evidence
# has_iron_evidence 短路升 high),设 0.03 是为加权综合分有少量贡献。
DIMENSION_WEIGHTS: dict[str, float] = {
    "text_similarity": 0.12,
    "section_similarity": 0.10,
    "structure_similarity": 0.08,
    "metadata_author": 0.10,
    "metadata_time": 0.08,
    "metadata_machine": 0.10,
    "price_consistency": 0.10,  # C12 释放部分权重给 price_anomaly
    "price_anomaly": 0.07,  # C12 新增
    "error_consistency": 0.10,  # fix-bug-triple I-Weight-1:0.12→0.10 释放 0.02
    "style": 0.07,  # fix-bug-triple I-Weight-1:0.08→0.07 释放 0.01
    "image_reuse": 0.02,  # fix-bug-triple I-Weight-1:0.05→0.02 释放 0.03
    "price_total_match": 0.03,  # fix-bug-triple 新增,任意两家总额相等(铁证)
    "price_overshoot": 0.03,  # fix-bug-triple 新增,任一超过最高限价(铁证)
}

# 7 个 pair 类维度(由 pair agent 写 PairComparison,judge 补写 OA 聚合行)
# fix-bug-triple:price_total_match / price_overshoot 是新加 global,从 PAIR_DIMENSIONS 排除
PAIR_DIMENSIONS: frozenset[str] = frozenset(DIMENSION_WEIGHTS.keys()) - {
    "error_consistency",
    "price_anomaly",
    "style",
    "image_reuse",
    "price_total_match",
    "price_overshoot",
}


# ============================================================ Shared Helpers


def _compute_dims_and_iron(
    pair_comparisons: Iterable[PairComparison],
    overall_analyses: Iterable[OverallAnalysis],
    *,
    adjusted_pcs: dict[int, dict] | None = None,
    adjusted_oas: dict[int, dict] | None = None,
) -> tuple[dict[str, float], bool, list[str]]:
    """共享 helper(C14 抽出避免双重实现):

    - per_dim_max[dim]:每维度跨 pair/global 的最高分
    - has_ironclad:任一 PC.is_ironclad 或任一 OA.evidence_json["has_iron_evidence"]=true
    - ironclad_dims:触发铁证的维度名列表(去重排序)

    CH-2 detect-template-exclusion:扩 keyword-only `adjusted_pcs / adjusted_oas`
    可选参数(向后兼容,默认 None 时行为完全不变);任一非 None 时,score 与
    is_ironclad/has_iron_evidence 优先读 adjusted dict 缺失回落 ORM raw。
    """
    use_apcs = adjusted_pcs is not None
    use_aoas = adjusted_oas is not None
    apcs = adjusted_pcs or {}
    aoas = adjusted_oas or {}

    per_dim_max: dict[str, float] = {}
    ironclad_dim_set: set[str] = set()

    for pc in pair_comparisons:
        if use_apcs and pc.id in apcs and "score" in apcs[pc.id]:
            score = float(apcs[pc.id]["score"])
        else:
            score = float(pc.score) if pc.score is not None else 0.0
        if pc.dimension not in per_dim_max or score > per_dim_max[pc.dimension]:
            per_dim_max[pc.dimension] = score
        if use_apcs and pc.id in apcs and "is_ironclad" in apcs[pc.id]:
            iron = bool(apcs[pc.id]["is_ironclad"])
        else:
            iron = bool(pc.is_ironclad)
        if iron:
            ironclad_dim_set.add(pc.dimension)

    for oa in overall_analyses:
        if use_aoas and oa.id in aoas and "score" in aoas[oa.id]:
            score = float(aoas[oa.id]["score"])
        else:
            score = float(oa.score) if oa.score is not None else 0.0
        if oa.dimension not in per_dim_max or score > per_dim_max[oa.dimension]:
            per_dim_max[oa.dimension] = score
        if use_aoas and oa.id in aoas and "has_iron_evidence" in aoas[oa.id]:
            has_iron = bool(aoas[oa.id]["has_iron_evidence"])
        else:
            ev = getattr(oa, "evidence_json", None) or {}
            has_iron = (
                isinstance(ev, dict) and ev.get("has_iron_evidence") is True
            )
        if has_iron:
            ironclad_dim_set.add(oa.dimension)

    has_ironclad = bool(ironclad_dim_set)
    return per_dim_max, has_ironclad, sorted(ironclad_dim_set)


def _compute_level(
    total: float, risk_levels: dict[str, int] | None = None
) -> str:
    """总分 → risk_level 映射。

    C17: risk_levels 参数可覆盖默认阈值（从 SystemConfig 传入）。
    默认：≥70 high / 40-69 medium / <40 low
    """
    high_threshold = 70
    medium_threshold = 40
    if risk_levels:
        high_threshold = risk_levels.get("high", 70)
        medium_threshold = risk_levels.get("medium", 40)
    if total >= high_threshold:
        return "high"
    elif total >= medium_threshold:
        return "medium"
    else:
        return "low"


def _compute_formula_total(
    per_dim_max: dict[str, float],
    has_ironclad: bool,
    weights: dict[str, float] | None = None,
) -> float:
    """加权求和 + 铁证强制 ≥85 + 四舍五入 2 位。纯函数。

    C17: weights 参数可覆盖 DIMENSION_WEIGHTS（从 SystemConfig 传入）。
    """
    w = weights if weights is not None else DIMENSION_WEIGHTS
    total = sum(
        per_dim_max.get(dim, 0.0) * weight
        for dim, weight in w.items()
    )
    if has_ironclad:
        total = max(total, 85.0)
    return round(total, 2)


# ============================================================ CH-2 Template Cluster


async def _load_bidder_metadata(
    session, project_id: int
) -> dict[int, list[DocumentMetadata]]:
    """加载 project 下每个 bidder 名下 file_role in TEMPLATE_FILE_ROLES 的 metadata。

    SQL 约束:
    - Bidder.project_id == project_id and Bidder.deleted_at IS NULL
    - BidDocument.bidder_id == Bidder.id
    - BidDocument.file_role in TEMPLATE_FILE_ROLES(排除 qualification PDF 噪音 + other)
    - DocumentMetadata.bid_document_id == BidDocument.id

    缺 metadata 的文档(metadata 行不存在)自动跳过(LEFT JOIN 后过滤 None)。
    """
    stmt = (
        select(Bidder.id, DocumentMetadata)
        .join(BidDocument, BidDocument.bidder_id == Bidder.id)
        .join(
            DocumentMetadata,
            DocumentMetadata.bid_document_id == BidDocument.id,
        )
        .where(
            Bidder.project_id == project_id,
            Bidder.deleted_at.is_(None),
            BidDocument.file_role.in_(TEMPLATE_FILE_ROLES),
        )
    )
    rows = (await session.execute(stmt)).all()
    by_bidder: dict[int, list[DocumentMetadata]] = {}
    for bidder_id, meta in rows:
        if meta is None:
            continue
        by_bidder.setdefault(bidder_id, []).append(meta)
    return by_bidder


# ======================================================== Pure compute_report


def compute_report(
    pair_comparisons: Iterable[PairComparison],
    overall_analyses: Iterable[OverallAnalysis],
) -> tuple[float, str]:
    """纯函数:加权计分 → (total_score, risk_level)。C6 契约不变。

    - 每维度取跨 pair/global 最高分
    - 铁证命中(任一 PC.is_ironclad=true 或任一 OA.evidence.has_iron_evidence=true)
      → total_score 强制 ≥ 85
    - 阈值:≥70 high;40-69 medium;<40 low
    """
    pcs = list(pair_comparisons)
    oas = list(overall_analyses)
    per_dim_max, has_ironclad, _ = _compute_dims_and_iron(pcs, oas)
    total = _compute_formula_total(per_dim_max, has_ironclad)
    return total, _compute_level(total)


# ======================================================== L-9 Clamp


def _clamp_with_llm(
    formula_total: float,
    llm_suggested: float,
    has_ironclad: bool,
) -> float:
    """L-9 clamp 严格 4 步:max(formula, llm) → 铁证 max(_, 85) → min(_, 100) → round 2 位

    LLM 只能升分,不能降;铁证硬下限 85 守护;天花板 100。
    """
    final = max(formula_total, llm_suggested)
    if has_ironclad:
        final = max(final, 85.0)
    final = min(final, 100.0)
    return round(final, 2)


# ======================================================= judge_and_create_report


async def judge_and_create_report(
    project_id: int,
    version: int,
    *,
    llm_provider: LLMProvider | None = None,
    rules_config: dict | None = None,
) -> None:
    """加载 pair + overall → 公式 → L-9 LLM → clamp → INSERT AnalysisReport

    幂等:若已有 (project_id, version) 的 AnalysisReport 行则跳过。

    C17: rules_config 来自 engine.py 的 config_to_engine_params()，
    包含 weights / risk_levels / enabled / dim_thresholds 等。

    LLM 注入策略:
    - 默认 llm_provider=None → 从 factory 取 default provider(生产路径)
    - 测试可显式传 provider 或 mock `call_llm_judge`(fixture `mock_llm_l9_*`)
    """
    async with async_session() as session:
        # 幂等检查
        existing_stmt = select(AnalysisReport).where(
            AnalysisReport.project_id == project_id,
            AnalysisReport.version == version,
        )
        existing = (await session.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "detect: AnalysisReport already exists project=%s v=%s, skip",
                project_id,
                version,
            )
            return

        # 加载 PC / OA
        pc_stmt = select(PairComparison).where(
            PairComparison.project_id == project_id,
            PairComparison.version == version,
        )
        pair_comparisons = list((await session.execute(pc_stmt)).scalars().all())

        oa_stmt = select(OverallAnalysis).where(
            OverallAnalysis.project_id == project_id,
            OverallAnalysis.version == version,
        )
        overall_analyses = list((await session.execute(oa_stmt)).scalars().all())

        # C17: 从 rules_config 提取 weights / risk_levels（若有）
        _weights = (
            rules_config.get("weights") if rules_config else None
        )
        _risk_levels = (
            rules_config.get("risk_levels") if rules_config else None
        )

        # CH-2 detect-template-exclusion 6 步调用顺序改造
        # ─────────────────────────────────────────────────────────────
        # step1: PC + OA 已加载(L218-L224)
        # step2: 第一次 _compute_dims_and_iron(raw) — 仅供 DEF-OA 写入复用
        raw_per_dim_max, raw_has_ironclad, raw_ironclad_dims = _compute_dims_and_iron(
            pair_comparisons, overall_analyses
        )

        # step3: DEF-OA 写入循环(用 raw,符合 D7 审计原则)+ local list 同步
        existing_oa_dims = {oa.dimension for oa in overall_analyses}
        for dim in PAIR_DIMENSIONS:
            if dim in existing_oa_dims:
                continue  # 幂等: 已有 OA 行则跳过
            dim_pcs = [pc for pc in pair_comparisons if pc.dimension == dim]
            best_score = raw_per_dim_max.get(dim, 0.0)
            iron_pcs = [pc for pc in dim_pcs if pc.is_ironclad]
            oa = OverallAnalysis(
                project_id=project_id,
                version=version,
                dimension=dim,
                score=Decimal(str(round(best_score, 2))),
                evidence_json={
                    "source": "pair_aggregation",
                    "best_score": round(best_score, 2),
                    "has_iron_evidence": len(iron_pcs) > 0,
                    "pair_count": len(dim_pcs),
                    "ironclad_pair_count": len(iron_pcs),
                },
            )
            session.add(oa)
            overall_analyses.append(oa)  # 同步 local list,确保后续 helper 见 11 行
        await session.flush()  # 7 个 def_oa 全部 flush 拿到 PK

        # step4: load bidder metadata + 模板簇识别
        try:
            bidder_metadata_map = await _load_bidder_metadata(
                session, project_id
            )
            clusters = _detect_template_cluster(bidder_metadata_map)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "detect: template cluster detection failed project=%s v=%s err=%s",
                project_id,
                version,
                exc,
            )
            clusters = []

        # detect-tender-baseline §2 step5.1: baseline_resolver 生产者
        # 按 dimension 分组调 produce_baseline_adjustments;tender > consensus > none
        # 优先级在 _apply_template_adjustments 内合并阶段处理。
        baseline_adjustments: list[Adjustment] = []
        try:
            dims_in_pcs = sorted({pc.dimension for pc in pair_comparisons})
            for dim in dims_in_pcs:
                dim_pcs = [pc for pc in pair_comparisons if pc.dimension == dim]
                if not dim_pcs:
                    continue
                baseline_adjustments.extend(
                    await baseline_resolver.produce_baseline_adjustments(
                        session, project_id, dim, dim_pcs
                    )
                )
        except Exception as exc:  # noqa: BLE001 - fail-soft,不阻塞 judge
            logger.error(
                "detect: baseline_resolver failed project=%s v=%s err=%s",
                project_id,
                version,
                exc,
            )
            baseline_adjustments = []

        # step5.2: adjustment(metadata cluster 自产 + baseline 喂入合并应用)
        adjusted_pcs, adjusted_oas, adjustments = _apply_template_adjustments(
            pair_comparisons,
            overall_analyses,
            clusters,
            extra_adjustments=baseline_adjustments,
        )

        # step6: 任一 adjustment(metadata cluster 或 baseline)命中时切到 adjusted 版本
        # detect-tender-baseline §2:adjustments 已合并 metadata + baseline,
        # cluster_active 现在表达的是"adjustments 活跃",而 metadata cluster 单独由
        # bool(clusters) 判断(供 AnalysisReport.template_cluster_detected 使用)。
        cluster_active = bool(adjustments)
        metadata_cluster_active = bool(clusters)
        if cluster_active:
            # step6.1: 第二次 _compute_dims_and_iron(adjusted)
            per_dim_max, has_ironclad, ironclad_dims = _compute_dims_and_iron(
                pair_comparisons,
                overall_analyses,
                adjusted_pcs=adjusted_pcs,
                adjusted_oas=adjusted_oas,
            )
        else:
            per_dim_max, has_ironclad, ironclad_dims = (
                raw_per_dim_max,
                raw_has_ironclad,
                raw_ironclad_dims,
            )

        # step6.2: _compute_formula_total(保留 weights=_weights C17 透传)
        formula_total = _compute_formula_total(
            per_dim_max, has_ironclad, weights=_weights
        )
        # step6.3: _compute_level(保留 risk_levels=_risk_levels C17 透传)
        formula_level = _compute_level(formula_total, risk_levels=_risk_levels)

        # 项目元信息
        project = await session.get(Project, project_id)
        bidder_count_stmt = (
            select(Bidder)
            .where(
                Bidder.project_id == project_id,
                Bidder.deleted_at.is_(None),
            )
        )
        bidder_count = len(
            list((await session.execute(bidder_count_stmt)).scalars().all())
        )
        project_info = {
            "id": project_id,
            "name": project.name if project is not None else "",
            "bidder_count": bidder_count,
        }

        # honest-detection-results D1 + CH-2 step6.4: 证据不足前置判定
        # cluster 命中走新分母(OA.score 切分母 + adjusted iron);否则走老 AgentTask 分母
        at_stmt = select(AgentTask).where(
            AgentTask.project_id == project_id,
            AgentTask.version == version,
        )
        agent_tasks = list((await session.execute(at_stmt)).scalars().all())
        evidence_kwargs = (
            {"adjusted_pcs": adjusted_pcs, "adjusted_oas": adjusted_oas}
            if cluster_active
            else {}
        )
        if not judge_llm._has_sufficient_evidence(
            agent_tasks, pair_comparisons, overall_analyses, **evidence_kwargs
        ):
            logger.info(
                "detect: insufficient evidence project=%s v=%s, skip LLM judge",
                project_id,
                version,
            )
            final_total = formula_total
            final_level = "indeterminate"
            final_conclusion = judge_llm.INSUFFICIENT_EVIDENCE_CONCLUSION
            llm_conclusion = None  # 用于后面 logger 标注
        else:
            # step6.5: L-9 LLM 综合研判(summarize 透传 adjusted dict)
            cfg = judge_llm.load_llm_judge_config()
            l9_kwargs = (
                {"adjusted_pcs": adjusted_pcs, "adjusted_oas": adjusted_oas}
                if cluster_active
                else {}
            )
            llm_conclusion, llm_suggested = await _run_l9(
                pair_comparisons,
                overall_analyses,
                per_dim_max,
                ironclad_dims,
                formula_total=formula_total,
                formula_level=formula_level,
                has_ironclad=has_ironclad,
                project_info=project_info,
                cfg=cfg,
                provider=llm_provider,
                **l9_kwargs,
            )

            # clamp(LLM 成功) or 降级(LLM 失败)
            if llm_conclusion is not None and llm_suggested is not None:
                final_total = _clamp_with_llm(
                    formula_total, llm_suggested, has_ironclad
                )
                final_level = _compute_level(final_total, risk_levels=_risk_levels)
                final_conclusion = llm_conclusion
            else:
                final_total = formula_total
                final_level = formula_level
                final_conclusion = judge_llm.fallback_conclusion(
                    final_total, final_level, per_dim_max, ironclad_dims
                )

        # CH-2 / detect-tender-baseline §2:构造 template_cluster_adjusted_scores JSONB
        # 任一 adjustment(metadata cluster 或 baseline)命中时,该 JSONB 非空。
        # clusters 字段可能为空(纯 baseline 命中场景),adjustments 是合并后的清单。
        if cluster_active:
            adjusted_scores_jsonb = {
                "clusters": [
                    {
                        "cluster_key_sample": c.cluster_key_sample,
                        "bidder_ids": c.bidder_ids,
                    }
                    for c in clusters
                ],
                "adjustments": list(adjustments),
            }
        else:
            adjusted_scores_jsonb = None

        # INSERT AnalysisReport
        report = AnalysisReport(
            project_id=project_id,
            version=version,
            total_score=Decimal(str(final_total)),
            risk_level=final_level,
            llm_conclusion=final_conclusion,
            # template_cluster_detected 仅表"metadata 簇识别成功",不含 baseline-only 命中
            # (baseline 命中通过 evidence_json.baseline_source 表达,前端 Badge 区分)
            template_cluster_detected=metadata_cluster_active,
            template_cluster_adjusted_scores=adjusted_scores_jsonb,
        )
        session.add(report)

        # project 状态回填
        if project is not None:
            project.status = "completed"
            project.risk_level = final_level

        await session.commit()
        await session.refresh(report)

    # fix-bug-triple-and-direction-high P3:project_status_changed MUST 先于 report_ready 推送,
    # 避免前端 race(Tag 已切"已完成" 但 latestReport 未到导致报告入口缺失)。
    if project is not None:
        await progress_broker.publish(
            project_id,
            "project_status_changed",
            {"new_status": "completed"},
        )

    # 推送 report_ready
    await progress_broker.publish(
        project_id,
        "report_ready",
        {
            "version": version,
            "total_score": final_total,
            "risk_level": final_level,
        },
    )
    logger.info(
        "detect: report ready project=%s v=%s score=%s level=%s llm=%s",
        project_id,
        version,
        final_total,
        final_level,
        "ok" if llm_conclusion is not None else "degraded",
    )


async def _run_l9(
    pair_comparisons,
    overall_analyses,
    per_dim_max: dict[str, float],
    ironclad_dims: list[str],
    *,
    formula_total: float,
    formula_level: str,
    has_ironclad: bool,
    project_info: dict,
    cfg: judge_llm.LLMJudgeConfig,
    provider: LLMProvider | None,
    adjusted_pcs: dict[int, dict] | None = None,
    adjusted_oas: dict[int, dict] | None = None,
) -> tuple[str | None, float | None]:
    """L-9 流水线单独抽:ENABLED=false → 返 (None, None) 走降级;否则调 LLM。

    CH-2 detect-template-exclusion:扩 adjusted_pcs/adjusted_oas kwarg 透传给
    summarize,防 LLM 拿污染 raw 值输出高 suggested_total → clamp 拉回污染分。
    """
    if not cfg.enabled:
        logger.info("L-9 disabled by env, skip")
        return None, None

    summary = judge_llm.summarize(
        pair_comparisons,
        overall_analyses,
        per_dim_max,
        ironclad_dims,
        formula_total=formula_total,
        formula_level=formula_level,
        has_ironclad=has_ironclad,
        project_info=project_info,
        top_k=cfg.summary_top_k,
        adjusted_pcs=adjusted_pcs,
        adjusted_oas=adjusted_oas,
    )

    # provider 注入:测试默认 None + 被 mock 直接 patch call_llm_judge;
    # 生产默认从 factory 取
    if provider is None:
        try:
            from app.services.llm.factory import get_llm_provider

            provider = get_llm_provider()
        except Exception as exc:  # noqa: BLE001
            logger.warning("L-9 get_llm_provider failed: %s", exc)
            return None, None

    return await judge_llm.call_llm_judge(
        summary, formula_total, provider=provider, cfg=cfg
    )


__all__ = [
    "DIMENSION_WEIGHTS",
    "compute_report",
    "judge_and_create_report",
]
