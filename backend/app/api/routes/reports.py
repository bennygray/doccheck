"""C6 报告骨架 API + C15 扩展

C6 (既有):
- GET /api/projects/{pid}/reports/{version} — Tab1 总览骨架(dimensions 聚合)

C15 扩展:
- 上述总览响应额外返回 manual_review_* 4 字段
- GET /reports/{version}/dimensions — 11 维度明细(evidence_summary + manual_review_json)
- GET /reports/{version}/pairs — PairComparison 行摘要(支持 sort/limit)
- GET /reports/{version}/logs — AgentTask + AuditLog 合并流(支持 source 过滤)
"""

from __future__ import annotations

import json
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.audit_log import AuditLog
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.schemas.report import (
    LogEntry,
    LogsResponse,
    PairComparisonItem,
    PairsResponse,
    ReportDimension,
    ReportDimensionDetail,
    ReportDimensionsResponse,
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
        # C15 复核字段(未复核为 null)
        manual_review_status=report.manual_review_status,
        manual_review_comment=report.manual_review_comment,
        reviewer_id=report.reviewer_id,
        reviewed_at=report.reviewed_at,
    )


# ================================================================= C15


def _evidence_summary(evidence_json: dict | None, fallback: str | None) -> str:
    """从 evidence_json 抽 1 句摘要。没有则回退到 PC.summary。"""
    if not evidence_json:
        return fallback or ""
    # 常见约定字段
    for key in ("summary", "reason", "conclusion"):
        val = evidence_json.get(key)
        if isinstance(val, str) and val:
            return val
    # 兜底:json dump 截断
    try:
        dumped = json.dumps(evidence_json, ensure_ascii=False)
    except (TypeError, ValueError):
        return fallback or ""
    return dumped[:200]


@router.get(
    "/{project_id}/reports/{version}/dimensions",
    response_model=ReportDimensionsResponse,
)
async def get_report_dimensions(
    project_id: int,
    version: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportDimensionsResponse:
    await _fetch_visible_project(session, user, project_id)

    # 校验报告存在(保持 404 行为)
    ar = (
        await session.execute(
            select(AnalysisReport).where(
                AnalysisReport.project_id == project_id,
                AnalysisReport.version == version,
            )
        )
    ).scalar_one_or_none()
    if ar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")

    oa_rows = (
        await session.execute(
            select(OverallAnalysis).where(
                OverallAnalysis.project_id == project_id,
                OverallAnalysis.version == version,
            )
        )
    ).scalars().all()
    pc_rows = (
        await session.execute(
            select(PairComparison).where(
                PairComparison.project_id == project_id,
                PairComparison.version == version,
            )
        )
    ).scalars().all()

    # 聚合:每维度 best_score / is_ironclad / evidence_summary / review
    best_score: dict[str, float] = defaultdict(float)
    iron: dict[str, bool] = defaultdict(bool)
    # 存最佳分来源的 evidence_json(OA 或 PC)
    best_evidence: dict[str, dict | None] = {}
    review: dict[str, dict | None] = {}

    # 先用 OA 奠基(单行/dim)
    for oa in oa_rows:
        score = float(oa.score) if oa.score is not None else 0.0
        if score > best_score[oa.dimension]:
            best_score[oa.dimension] = score
            best_evidence[oa.dimension] = oa.evidence_json
        if (
            oa.evidence_json
            and oa.evidence_json.get("has_iron_evidence") is True
        ):
            iron[oa.dimension] = True
        review[oa.dimension] = oa.manual_review_json

    # PC 追加:score 更高替换;铁证合并
    for pc in pc_rows:
        score = float(pc.score) if pc.score is not None else 0.0
        if score > best_score[pc.dimension]:
            best_score[pc.dimension] = score
            best_evidence[pc.dimension] = pc.evidence_json
        if pc.is_ironclad:
            iron[pc.dimension] = True

    # detect-tender-baseline §2:每维度 baseline_source 取最强 source
    # priority: tender(3) > consensus(2) > metadata_cluster(1) > none(0)
    # 数据源:① OA/PC 的 evidence_json.baseline_source(detector §3+ 写入)
    #        ② AnalysisReport.template_cluster_adjusted_scores.adjustments[].baseline_source
    # warnings 数组同样按维度合并(去重保序)。
    baseline_priority = {"tender": 3, "consensus": 2, "metadata_cluster": 1, "none": 0}
    baseline_source: dict[str, str] = defaultdict(lambda: "none")
    warnings_by_dim: dict[str, list[str]] = defaultdict(list)

    def _bump_source(dim: str, src: str | None) -> None:
        if not src:
            return
        if baseline_priority.get(src, -1) > baseline_priority.get(
            baseline_source[dim], 0
        ):
            baseline_source[dim] = src

    def _extend_warnings(dim: str, ws: list[str] | None) -> None:
        if not ws:
            return
        for w in ws:
            if w and w not in warnings_by_dim[dim]:
                warnings_by_dim[dim].append(w)

    for oa in oa_rows:
        if isinstance(oa.evidence_json, dict):
            _bump_source(oa.dimension, oa.evidence_json.get("baseline_source"))
            _extend_warnings(oa.dimension, oa.evidence_json.get("warnings"))
    for pc in pc_rows:
        if isinstance(pc.evidence_json, dict):
            _bump_source(pc.dimension, pc.evidence_json.get("baseline_source"))
            _extend_warnings(pc.dimension, pc.evidence_json.get("warnings"))

    # AnalysisReport.template_cluster_adjusted_scores 兜底(detector 未写时仍可推导)
    if isinstance(ar.template_cluster_adjusted_scores, dict):
        for adj in ar.template_cluster_adjusted_scores.get("adjustments", []) or []:
            if not isinstance(adj, dict):
                continue
            dim = adj.get("dimension")
            if not dim:
                continue
            # baseline_source 直接来自 adjustment 字段;否则按 reason 反推
            src = adj.get("baseline_source")
            if not src:
                reason = adj.get("reason", "")
                if reason == "tender_match":
                    src = "tender"
                elif reason == "consensus_match":
                    src = "consensus"
                elif reason and reason.startswith("template_cluster"):
                    src = "metadata_cluster"
            _bump_source(dim, src)

    # 构造响应,顺序 = DIMENSION_WEIGHTS
    items: list[ReportDimensionDetail] = []
    for dim in DIMENSION_WEIGHTS.keys():
        items.append(
            ReportDimensionDetail(
                dimension=dim,
                best_score=best_score.get(dim, 0.0),
                is_ironclad=iron.get(dim, False),
                evidence_summary=_evidence_summary(best_evidence.get(dim), None),
                manual_review_json=review.get(dim),
                baseline_source=baseline_source.get(dim, "none"),
                warnings=warnings_by_dim.get(dim, []),
            )
        )
    return ReportDimensionsResponse(dimensions=items)


@router.get(
    "/{project_id}/reports/{version}/pairs",
    response_model=PairsResponse,
)
async def get_report_pairs(
    project_id: int,
    version: int,
    sort: str = Query(default="score_desc"),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PairsResponse:
    await _fetch_visible_project(session, user, project_id)

    ar = (
        await session.execute(
            select(AnalysisReport).where(
                AnalysisReport.project_id == project_id,
                AnalysisReport.version == version,
            )
        )
    ).scalar_one_or_none()
    if ar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")

    stmt = select(PairComparison).where(
        PairComparison.project_id == project_id,
        PairComparison.version == version,
    )
    if sort == "score_desc":
        stmt = stmt.order_by(PairComparison.score.desc().nullslast())
    else:
        stmt = stmt.order_by(PairComparison.id.asc())
    stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).scalars().all()

    items = [
        PairComparisonItem(
            id=pc.id,
            dimension=pc.dimension,
            bidder_a_id=pc.bidder_a_id,
            bidder_b_id=pc.bidder_b_id,
            score=float(pc.score) if pc.score is not None else 0.0,
            is_ironclad=bool(pc.is_ironclad),
            evidence_summary=_evidence_summary(pc.evidence_json, None),
            # detect-tender-baseline §2:老 evidence 缺该字段时默认 "none"
            baseline_source=(
                (pc.evidence_json or {}).get("baseline_source", "none")
                if isinstance(pc.evidence_json, dict)
                else "none"
            ),
        )
        for pc in rows
    ]
    return PairsResponse(items=items)


@router.get(
    "/{project_id}/reports/{version}/logs",
    response_model=LogsResponse,
)
async def get_report_logs(
    project_id: int,
    version: int,
    source: str = Query(default="all", pattern="^(all|agent_task|audit_log)$"),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LogsResponse:
    await _fetch_visible_project(session, user, project_id)

    ar = (
        await session.execute(
            select(AnalysisReport).where(
                AnalysisReport.project_id == project_id,
                AnalysisReport.version == version,
            )
        )
    ).scalar_one_or_none()
    if ar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")

    merged: list[LogEntry] = []

    if source in ("all", "agent_task"):
        at_rows = (
            await session.execute(
                select(AgentTask)
                .where(
                    AgentTask.project_id == project_id,
                    AgentTask.version == version,
                )
                .order_by(AgentTask.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        for t in at_rows:
            # summary 字段在 AgentTask 中是 String(500) 的 short 描述;
            # error 是 failure text
            merged.append(
                LogEntry(
                    source="agent_task",
                    created_at=t.created_at,
                    payload={
                        "id": t.id,
                        "agent_name": t.agent_name,
                        "agent_type": t.agent_type,
                        "status": t.status,
                        "score": float(t.score) if t.score is not None else None,
                        "summary": getattr(t, "summary", None),
                        "error": getattr(t, "error", None),
                    },
                )
            )

    if source in ("all", "audit_log"):
        al_rows = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.project_id == project_id,
                    AuditLog.report_id == ar.id,
                )
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        for a in al_rows:
            merged.append(
                LogEntry(
                    source="audit_log",
                    created_at=a.created_at,
                    payload={
                        "id": a.id,
                        "action": a.action,
                        "actor_id": a.actor_id,
                        "target_type": a.target_type,
                        "target_id": a.target_id,
                        "before_json": a.before_json,
                        "after_json": a.after_json,
                    },
                )
            )

    # 合并后全局按 created_at DESC 并 trim
    merged.sort(key=lambda e: e.created_at, reverse=True)
    merged = merged[:limit]

    return LogsResponse(items=merged)


__all__ = ["router"]
