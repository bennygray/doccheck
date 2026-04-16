"""Word 导出 endpoints (C15 report-export)

- POST /api/projects/{pid}/reports/{version}/export  触发异步导出,返 202 + {job_id}
- GET  /api/exports/{job_id}/download                下载(200/410/409/404)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.analysis_report import AnalysisReport
from app.models.export_job import ExportJob
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.services import audit as audit_service

logger = logging.getLogger(__name__)

# 两个独立 router:一个挂 /api/projects,一个挂 /api/exports
projects_router = APIRouter()
exports_router = APIRouter()


class ExportIn(BaseModel):
    template_id: int | None = None


class ExportStartOut(BaseModel):
    job_id: int


# ================================================================= 触发


@projects_router.post(
    "/{project_id}/reports/{version}/export",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ExportStartOut,
)
async def start_export(
    project_id: int,
    version: int,
    body: ExportIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExportStartOut:
    # 权限 + 报告存在
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

    job = ExportJob(
        project_id=project_id,
        report_id=ar.id,
        actor_id=user.id,
        template_id=body.template_id,
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    # audit_log
    await audit_service.log_action(
        action="export.requested",
        project_id=project_id,
        report_id=ar.id,
        actor_id=user.id,
        target_type="export",
        target_id=str(job.id),
        after={"template_id": body.template_id},
        request=request,
    )

    # 异步调度(允许测试通过 env 禁用)
    import os

    if os.environ.get("C15_DISABLE_EXPORT_WORKER") != "1":
        # 局部导入避免循环
        from app.services.export.worker import run_export

        asyncio.create_task(run_export(job.id))

    return ExportStartOut(job_id=job.id)


# ================================================================= 下载


@exports_router.get("/{job_id}/download")
async def download_export(
    job_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = await session.get(ExportJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "导出任务不存在")
    # 权限:project owner 或 admin
    stmt = get_visible_projects_stmt(user).where(Project.id == job.project_id)
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "导出任务不存在")

    if job.file_expired:
        raise HTTPException(
            status.HTTP_410_GONE,
            detail={
                "error": "file_expired",
                "hint": "点击重新生成",
            },
        )
    if job.status != "succeeded":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error": "job_not_ready", "status": job.status},
        )
    if not job.file_path:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error": "file_path_missing"},
        )
    path = Path(job.file_path)
    if not path.exists():
        raise HTTPException(
            status.HTTP_410_GONE,
            detail={"error": "file_expired", "hint": "点击重新生成"},
        )

    # 下载记 audit_log
    ar = await session.get(AnalysisReport, job.report_id)
    filename = (
        f"report_{job.project_id}_v{ar.version}_{job.id}.docx"
        if ar
        else f"report_{job.id}.docx"
    )
    await audit_service.log_action(
        action="export.downloaded",
        project_id=job.project_id,
        report_id=job.report_id,
        actor_id=user.id,
        target_type="export",
        target_id=str(job.id),
        request=request,
    )
    return FileResponse(
        path=str(path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


__all__ = ["projects_router", "exports_router"]
