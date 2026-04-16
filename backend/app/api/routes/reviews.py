"""人工复核端点 (C15 report-export, spec manual-review)

- POST /api/projects/{pid}/reports/{version}/review          整报告级
- POST /api/projects/{pid}/reports/{version}/dimensions/{dim}/review  维度级

设计约束:
- 复核仅写入 manual_review_* 字段,不动 AR.total_score/risk_level/llm_conclusion/OA.score
- 非法 status / 不存在维度 / 无权限 → 400 / 404
- 成功后调用 audit.log_action 记 before/after 快照(写失败不影响响应)
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.analysis_report import MANUAL_REVIEW_STATUSES, AnalysisReport
from app.models.overall_analysis import OverallAnalysis
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.services import audit as audit_service
from app.services.detect.judge import DIMENSION_WEIGHTS

router = APIRouter()


# ============================================================ Schemas


class ReportReviewIn(BaseModel):
    status: str = Field(..., description="confirmed/rejected/downgraded/upgraded")
    comment: str | None = None


class ReportReviewOut(BaseModel):
    manual_review_status: str
    manual_review_comment: str | None
    reviewer_id: int
    reviewed_at: str


class DimensionReviewIn(BaseModel):
    action: str = Field(..., description="confirmed/rejected/note")
    comment: str | None = None


# 维度级 action 3 值枚举
_DIMENSION_ACTIONS = frozenset({"confirmed", "rejected", "note"})


# ============================================================ Helpers


async def _require_report(
    session: AsyncSession, user: User, project_id: int, version: int
) -> tuple[Project, AnalysisReport]:
    stmt = get_visible_projects_stmt(user).where(Project.id == project_id)
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
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
    return project, ar


# ============================================================ 整报告级


@router.post("/{project_id}/reports/{version}/review", response_model=ReportReviewOut)
async def review_report(
    project_id: int,
    version: int,
    body: ReportReviewIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportReviewOut:
    # 1) status 枚举校验
    if body.status not in MANUAL_REVIEW_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"status 必须是 {sorted(MANUAL_REVIEW_STATUSES)} 之一",
        )

    # 2) 权限 + 报告存在
    _, ar = await _require_report(session, user, project_id, version)

    # 3) 记 before 快照(复核前)
    before = {
        "status": ar.manual_review_status,
        "comment": ar.manual_review_comment,
    }

    # 4) 仅写 manual_review_* 字段;检测原值不动
    ar.manual_review_status = body.status
    ar.manual_review_comment = body.comment
    ar.reviewer_id = user.id
    ar.reviewed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(ar)

    # 5) audit_log(写失败不影响响应)
    after = {"status": ar.manual_review_status, "comment": ar.manual_review_comment}
    await audit_service.log_action(
        action=f"review.report_{body.status}",
        project_id=project_id,
        report_id=ar.id,
        actor_id=user.id,
        target_type="report",
        target_id=str(ar.id),
        before=before,
        after=after,
        request=request,
    )

    return ReportReviewOut(
        manual_review_status=ar.manual_review_status,
        manual_review_comment=ar.manual_review_comment,
        reviewer_id=ar.reviewer_id,
        reviewed_at=ar.reviewed_at.isoformat(),
    )


# ============================================================ 维度级


@router.post(
    "/{project_id}/reports/{version}/dimensions/{dim_name}/review"
)
async def review_dimension(
    project_id: int,
    version: int,
    dim_name: str,
    body: DimensionReviewIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    # 1) action 枚举校验
    if body.action not in _DIMENSION_ACTIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"action 必须是 {sorted(_DIMENSION_ACTIONS)} 之一",
        )

    # 2) 维度名是否合法
    if dim_name not in DIMENSION_WEIGHTS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"未知维度: {dim_name}"
        )

    # 3) 权限 + report 存在
    _, ar = await _require_report(session, user, project_id, version)

    # 4) OA 行存在(该 project+version+dimension)
    oa = (
        await session.execute(
            select(OverallAnalysis).where(
                OverallAnalysis.project_id == project_id,
                OverallAnalysis.version == version,
                OverallAnalysis.dimension == dim_name,
            )
        )
    ).scalar_one_or_none()
    if oa is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"维度 {dim_name} 无 OA 记录"
        )

    # 5) 写维度级标记(覆盖)
    before = oa.manual_review_json
    now_iso = datetime.now(timezone.utc).isoformat()
    oa.manual_review_json = {
        "action": body.action,
        "comment": body.comment,
        "reviewer_id": user.id,
        "at": now_iso,
    }
    await session.commit()

    # 6) audit_log
    await audit_service.log_action(
        action="review.dimension_marked",
        project_id=project_id,
        report_id=ar.id,
        actor_id=user.id,
        target_type="report_dimension",
        target_id=dim_name,
        before=before,
        after=oa.manual_review_json,
        request=request,
    )

    return {
        "dimension": dim_name,
        "manual_review_json": oa.manual_review_json,
    }


__all__ = ["router"]
