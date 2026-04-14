"""C6 报告骨架 API (detect-framework)

GET /api/projects/{pid}/reports/{version} — Tab1 总览骨架(详细 Tab 留 C14)。
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.schemas.report import (
    ReportDimension,
    ReportDimensionStatusCounts,
    ReportResponse,
)
from app.services.detect.judge import DIMENSION_WEIGHTS

router = APIRouter()

# 10 维度全集(即使无 AgentTask 产出也保底 0 分)
ALL_DIMENSIONS: tuple[str, ...] = tuple(DIMENSION_WEIGHTS.keys())


async def _fetch_visible_project(
    session: AsyncSession, user: User, project_id: int
) -> Project:
    stmt = get_visible_projects_stmt(user).where(Project.id == project_id)
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    return project


@router.get(
    "/{project_id}/reports/{version}",
    response_model=ReportResponse,
)
async def get_report(
    project_id: int,
    version: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportResponse:
    await _fetch_visible_project(session, user, project_id)

    report = (
        await session.execute(
            select(AnalysisReport).where(
                AnalysisReport.project_id == project_id,
                AnalysisReport.version == version,
            )
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在或正在生成")

    # 聚合 dimensions
    pair_rows = (
        await session.execute(
            select(PairComparison).where(
                PairComparison.project_id == project_id,
                PairComparison.version == version,
            )
        )
    ).scalars().all()
    overall_rows = (
        await session.execute(
            select(OverallAnalysis).where(
                OverallAnalysis.project_id == project_id,
                OverallAnalysis.version == version,
            )
        )
    ).scalars().all()
    agent_task_rows = (
        await session.execute(
            select(AgentTask).where(
                AgentTask.project_id == project_id,
                AgentTask.version == version,
            )
        )
    ).scalars().all()

    best_score: dict[str, float] = defaultdict(float)
    ironclad: dict[str, bool] = defaultdict(bool)
    for pc in pair_rows:
        score = float(pc.score) if pc.score is not None else 0.0
        if score > best_score[pc.dimension]:
            best_score[pc.dimension] = score
        if pc.is_ironclad:
            ironclad[pc.dimension] = True
    for oa in overall_rows:
        score = float(oa.score) if oa.score is not None else 0.0
        if score > best_score[oa.dimension]:
            best_score[oa.dimension] = score

    # status_counts 按 agent_name == dimension 聚合
    status_by_dim: dict[str, ReportDimensionStatusCounts] = {}
    summaries_by_dim: dict[str, list[str]] = defaultdict(list)
    for at in agent_task_rows:
        counts = status_by_dim.setdefault(
            at.agent_name, ReportDimensionStatusCounts()
        )
        if at.status in ("succeeded", "failed", "timeout", "skipped"):
            setattr(counts, at.status, getattr(counts, at.status) + 1)
        if at.summary:
            summaries_by_dim[at.agent_name].append(at.summary)

    dimensions: list[ReportDimension] = []
    for dim in ALL_DIMENSIONS:
        dimensions.append(
            ReportDimension(
                dimension=dim,
                best_score=best_score.get(dim, 0.0),
                is_ironclad=ironclad.get(dim, False),
                status_counts=status_by_dim.get(
                    dim, ReportDimensionStatusCounts()
                ),
                summaries=summaries_by_dim.get(dim, []),
            )
        )

    # 按 is_ironclad desc + best_score desc 排序
    dimensions.sort(key=lambda d: (not d.is_ironclad, -d.best_score))

    return ReportResponse(
        version=report.version,
        total_score=float(report.total_score),
        risk_level=report.risk_level,
        llm_conclusion=report.llm_conclusion or "",
        created_at=report.created_at,
        dimensions=dimensions,
    )


__all__ = ["router"]
