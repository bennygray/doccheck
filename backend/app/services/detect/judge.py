"""综合研判占位 (C6 detect-framework D4)

按 requirements §F-RP-01 的 10 维度加权求和 → total_score + risk_level;
铁证命中强制至少 high;LLM 结论字段留空,C14 接入真实 LLM。
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.analysis_report import AnalysisReport
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.services.parser.pipeline.progress_broker import progress_broker

logger = logging.getLogger(__name__)


# 11 维度权重,合计 1.00(D4 占位值;C14 可调)
# C12 新增 price_anomaly(占 0.07),从 price_consistency 0.15→0.10 + image_reuse 0.07→0.05 释放
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


def compute_report(
    pair_comparisons: Iterable[PairComparison],
    overall_analyses: Iterable[OverallAnalysis],
) -> tuple[float, str]:
    """纯函数:加权计分 → (total_score, risk_level)。

    - 每维度取跨 pair/global 最高分
    - 铁证命中(任一 PC.is_ironclad=true)→ total_score 强制 ≥ 85
    - 阈值:≥70 high;40-69 medium;<40 low
    """
    per_dim_max: dict[str, float] = {}

    has_ironclad = False
    for pc in pair_comparisons:
        score = float(pc.score) if pc.score is not None else 0.0
        prev = per_dim_max.get(pc.dimension, 0.0)
        if score > prev:
            per_dim_max[pc.dimension] = score
        if pc.is_ironclad:
            has_ironclad = True

    for oa in overall_analyses:
        score = float(oa.score) if oa.score is not None else 0.0
        prev = per_dim_max.get(oa.dimension, 0.0)
        if score > prev:
            per_dim_max[oa.dimension] = score

    total = sum(
        per_dim_max.get(dim, 0.0) * weight
        for dim, weight in DIMENSION_WEIGHTS.items()
    )

    if has_ironclad:
        total = max(total, 85.0)

    total = round(total, 2)

    if total >= 70:
        level = "high"
    elif total >= 40:
        level = "medium"
    else:
        level = "low"

    return total, level


async def judge_and_create_report(project_id: int, version: int) -> None:
    """加载 pair + overall → compute → INSERT AnalysisReport + UPDATE project + broker publish。

    幂等:若已有 (project_id, version) 的 AnalysisReport 行则跳过(UNIQUE 约束兜底)。
    """
    async with async_session() as session:
        # 检查是否已有报告(兜底幂等)
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

        total_score, risk_level = compute_report(pair_comparisons, overall_analyses)

        report = AnalysisReport(
            project_id=project_id,
            version=version,
            total_score=Decimal(str(total_score)),
            risk_level=risk_level,
            llm_conclusion="",  # C6 留空;C14 接 LLM 填
        )
        session.add(report)

        # 回填 project.status = 'completed' + risk_level
        project = await session.get(Project, project_id)
        if project is not None:
            project.status = "completed"
            project.risk_level = risk_level

        await session.commit()
        await session.refresh(report)

    # 推送 report_ready(聚合数据)
    await progress_broker.publish(
        project_id,
        "report_ready",
        {
            "version": version,
            "total_score": total_score,
            "risk_level": risk_level,
        },
    )
    logger.info(
        "detect: report ready project=%s v=%s score=%s level=%s",
        project_id,
        version,
        total_score,
        risk_level,
    )


__all__ = [
    "DIMENSION_WEIGHTS",
    "compute_report",
    "judge_and_create_report",
]
