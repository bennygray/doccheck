"""综合研判 (C6 骨架 + C14 L-9 LLM 接入)

C6: requirements §F-RP-01 10 维度加权求和 → total_score + risk_level;
    铁证命中强制至少 high;llm_conclusion 占位留空。
C12: 新增 price_anomaly global 维度(权重 0.07,从 price_consistency / image_reuse 释放)。
C13: judge.compute_report 扩读 OverallAnalysis.evidence_json["has_iron_evidence"] 支持 global 型铁证升级。
C14: 在 compute_report 之后插入 L-9 LLM 综合研判层(预聚合摘要 → LLM → 可升不可降 clamp →
     失败模板兜底)。compute_report 纯函数签名契约不变。
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401

from app.db.session import async_session
from app.models.analysis_report import AnalysisReport
from app.models.bidder import Bidder
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.services.detect import judge_llm
from app.services.llm.base import LLMProvider
from app.services.parser.pipeline.progress_broker import progress_broker

logger = logging.getLogger(__name__)


# 11 维度权重,合计 1.00(D4 占位值;C14 保持 C12 调整后的值,实战反馈调参留 follow-up)
DIMENSION_WEIGHTS: dict[str, float] = {
    "text_similarity": 0.12,
    "section_similarity": 0.10,
    "structure_similarity": 0.08,
    "metadata_author": 0.10,
    "metadata_time": 0.08,
    "metadata_machine": 0.10,
    "price_consistency": 0.10,  # C12 释放部分权重给 price_anomaly
    "price_anomaly": 0.07,  # C12 新增
    "error_consistency": 0.12,  # 铁证维度,权重最高之一
    "style": 0.08,
    "image_reuse": 0.05,  # C12 释放部分权重给 price_anomaly
}


# ============================================================ Shared Helpers


def _compute_dims_and_iron(
    pair_comparisons: Iterable[PairComparison],
    overall_analyses: Iterable[OverallAnalysis],
) -> tuple[dict[str, float], bool, list[str]]:
    """共享 helper(C14 抽出避免双重实现):

    - per_dim_max[dim]:每维度跨 pair/global 的最高分
    - has_ironclad:任一 PC.is_ironclad 或任一 OA.evidence_json["has_iron_evidence"]=true
    - ironclad_dims:触发铁证的维度名列表(去重排序)
    """
    per_dim_max: dict[str, float] = {}
    ironclad_dim_set: set[str] = set()

    for pc in pair_comparisons:
        score = float(pc.score) if pc.score is not None else 0.0
        prev = per_dim_max.get(pc.dimension, 0.0)
        if score > prev:
            per_dim_max[pc.dimension] = score
        if pc.is_ironclad:
            ironclad_dim_set.add(pc.dimension)

    for oa in overall_analyses:
        score = float(oa.score) if oa.score is not None else 0.0
        prev = per_dim_max.get(oa.dimension, 0.0)
        if score > prev:
            per_dim_max[oa.dimension] = score
        ev = getattr(oa, "evidence_json", None) or {}
        if isinstance(ev, dict) and ev.get("has_iron_evidence") is True:
            ironclad_dim_set.add(oa.dimension)

    has_ironclad = bool(ironclad_dim_set)
    return per_dim_max, has_ironclad, sorted(ironclad_dim_set)


def _compute_level(total: float) -> str:
    """总分 → risk_level 映射(≥70 high / 40-69 medium / <40 low)"""
    if total >= 70:
        return "high"
    elif total >= 40:
        return "medium"
    else:
        return "low"


def _compute_formula_total(
    per_dim_max: dict[str, float], has_ironclad: bool
) -> float:
    """加权求和 + 铁证强制 ≥85 + 四舍五入 2 位。纯函数。"""
    total = sum(
        per_dim_max.get(dim, 0.0) * weight
        for dim, weight in DIMENSION_WEIGHTS.items()
    )
    if has_ironclad:
        total = max(total, 85.0)
    return round(total, 2)


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
) -> None:
    """加载 pair + overall → 公式 → L-9 LLM → clamp → INSERT AnalysisReport

    幂等:若已有 (project_id, version) 的 AnalysisReport 行则跳过。

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

        # 公式层(compute_report 逻辑展开,供 L-9 复用 per_dim_max / ironclad_dims)
        per_dim_max, has_ironclad, ironclad_dims = _compute_dims_and_iron(
            pair_comparisons, overall_analyses
        )
        formula_total = _compute_formula_total(per_dim_max, has_ironclad)
        formula_level = _compute_level(formula_total)

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

        # L-9 LLM 综合研判
        cfg = judge_llm.load_llm_judge_config()
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
        )

        # clamp(LLM 成功) or 降级(LLM 失败)
        if llm_conclusion is not None and llm_suggested is not None:
            final_total = _clamp_with_llm(
                formula_total, llm_suggested, has_ironclad
            )
            final_level = _compute_level(final_total)
            final_conclusion = llm_conclusion
        else:
            final_total = formula_total
            final_level = formula_level
            final_conclusion = judge_llm.fallback_conclusion(
                final_total, final_level, per_dim_max, ironclad_dims
            )

        # INSERT AnalysisReport
        report = AnalysisReport(
            project_id=project_id,
            version=version,
            total_score=Decimal(str(final_total)),
            risk_level=final_level,
            llm_conclusion=final_conclusion,
        )
        session.add(report)

        # project 状态回填
        if project is not None:
            project.status = "completed"
            project.risk_level = final_level

        await session.commit()
        await session.refresh(report)

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
) -> tuple[str | None, float | None]:
    """L-9 流水线单独抽:ENABLED=false → 返 (None, None) 走降级;否则调 LLM"""
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
