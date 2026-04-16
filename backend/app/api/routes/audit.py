"""审计日志查询端点 (C15 report-export, spec audit-log §操作日志查询端点)

GET /api/projects/{project_id}/audit_logs — reviewer 自己项目 / admin 任意
支持 query:report_id / action 前缀 / limit / offset
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User

router = APIRouter()


async def _require_visible_project(
    session: AsyncSession, user: User, project_id: int
) -> Project:
    stmt = get_visible_projects_stmt(user).where(Project.id == project_id)
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    return project


@router.get("/{project_id}/audit_logs")
async def list_audit_logs(
    project_id: int,
    report_id: int | None = Query(default=None),
    action: str | None = Query(
        default=None,
        description="action 前缀过滤,如 'review.' 或 'export.'",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await _require_visible_project(session, user, project_id)

    stmt = select(AuditLog).where(AuditLog.project_id == project_id)
    if report_id is not None:
        stmt = stmt.where(AuditLog.report_id == report_id)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)

    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "project_id": r.project_id,
                "report_id": r.report_id,
                "actor_id": r.actor_id,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "before_json": r.before_json,
                "after_json": r.after_json,
                "ip": r.ip,
                "user_agent": r.user_agent,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
    }


__all__ = ["router"]
