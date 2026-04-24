"""run_export(job_id) — 异步 Word 导出执行器 (C15 report-export)

状态机 pending → running → succeeded | failed。
三兜底(design D4 + spec report-export §fallback):
1. 用户模板 load/render 失败 → 回退内置 + fallback_used=true + audit fallback_to_builtin
2. 内置模板渲染也失败 → status=failed + audit export.failed
3. 文件过期(7天)→ cleanup.py 标记,下载返 410
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session
from app.models.analysis_report import AnalysisReport
from app.models.export_job import ExportJob
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.services import audit as audit_service
from app.services.export.generator import build_render_context, render_to_file
from app.services.export.templates import (
    TemplateLoadError,
    builtin_template_path,
    load_template,
)
from app.services.parser.pipeline.progress_broker import progress_broker

logger = logging.getLogger(__name__)


def _export_dir() -> Path:
    # 复用现有 uploads 目录;export 子目录
    base = Path(getattr(settings, "upload_dir", "uploads"))
    return base / "exports"


def _output_path_for_job(job_id: int) -> Path:
    return _export_dir() / f"{job_id}.docx"


async def _publish(project_id: int, job_id: int, phase: str, progress: float, message: str = "") -> None:
    try:
        await progress_broker.publish(
            project_id,
            "export_progress",
            {
                "job_id": job_id,
                "phase": phase,
                "progress": progress,
                "message": message,
            },
        )
    except Exception as exc:  # noqa: BLE001 - SSE 发送失败不影响导出本身
        logger.warning("export progress publish failed job=%s err=%s", job_id, exc)


async def run_export(job_id: int) -> None:
    """执行一个导出 job。所有异常就地捕获,不抛给调用方(通常是 asyncio.create_task)。"""
    # 1) 初始化:置 running + started_at
    async with async_session() as session:
        job = await session.get(ExportJob, job_id)
        if job is None:
            logger.error("run_export: job %s not found", job_id)
            return
        if job.status != "pending":
            # 重复触发保护
            logger.warning(
                "run_export: job %s status=%s, skip",
                job_id,
                job.status,
            )
            return
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        project_id = job.project_id
        report_id = job.report_id
        template_id = job.template_id
        actor_id = job.actor_id
        await session.commit()

    await _publish(project_id, job_id, "rendering", 0.1, "准备导出数据")

    fallback_used = False
    output_path = _output_path_for_job(job_id)

    try:
        # 2) 加载数据
        async with async_session() as session:
            ar = await session.get(AnalysisReport, report_id)
            project = await session.get(Project, project_id)
            if ar is None or project is None:
                raise RuntimeError(
                    f"report {report_id} or project {project_id} missing"
                )
            oa_rows = (
                await session.execute(
                    select(OverallAnalysis).where(
                        OverallAnalysis.project_id == project_id,
                        OverallAnalysis.version == ar.version,
                    )
                )
            ).scalars().all()
            pc_rows = (
                await session.execute(
                    select(PairComparison).where(
                        PairComparison.project_id == project_id,
                        PairComparison.version == ar.version,
                    )
                )
            ).scalars().all()
            # honest-detection-results F3: 加载 bidders 以支持 identity_info_status 降级文案
            from app.models.bidder import Bidder

            bidder_rows = (
                await session.execute(
                    select(Bidder).where(
                        Bidder.project_id == project_id,
                        Bidder.deleted_at.is_(None),
                    )
                )
            ).scalars().all()

            context = build_render_context(
                project=project,
                ar=ar,
                oa_rows=oa_rows,
                pc_rows=pc_rows,
                bidders=bidder_rows,
            )

        await _publish(project_id, job_id, "rendering", 0.4, "渲染模板")

        # 3) 加载模板(带 fallback)
        template_path: Path | None = None
        if template_id is not None:
            try:
                async with async_session() as session:
                    template_path = await load_template(session, template_id)
            except TemplateLoadError as exc:
                logger.warning(
                    "template load failed job=%s template=%s err=%s",
                    job_id,
                    template_id,
                    exc,
                )
                fallback_used = True
            else:
                # 尝试用用户模板渲染 — 异常时 fallback
                try:
                    await _publish(
                        project_id, job_id, "writing", 0.7, "写入文件"
                    )
                    size = render_to_file(
                        template_path, context, output_path
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "user template render failed job=%s err=%s",
                        job_id,
                        exc,
                    )
                    fallback_used = True
                    size = None
                else:
                    await _finalize_success(
                        job_id=job_id,
                        project_id=project_id,
                        actor_id=actor_id,
                        report_id=report_id,
                        output_path=output_path,
                        size=size,
                        fallback_used=False,
                    )
                    return

        # 4) 内置模板路径(首选 or fallback 路径)
        if fallback_used and template_id is not None:
            await audit_service.log_action(
                action="export.fallback_to_builtin",
                project_id=project_id,
                report_id=report_id,
                actor_id=actor_id,
                target_type="export",
                target_id=str(job_id),
                before={"template_id": template_id},
                after={"fallback_template": "default.docx"},
            )

        builtin = builtin_template_path()
        await _publish(project_id, job_id, "writing", 0.7, "写入文件")
        size = render_to_file(builtin, context, output_path)

        await _finalize_success(
            job_id=job_id,
            project_id=project_id,
            actor_id=actor_id,
            report_id=report_id,
            output_path=output_path,
            size=size,
            fallback_used=fallback_used,
        )

    except Exception as exc:  # noqa: BLE001 - 真的失败就记 FAILED
        logger.exception("run_export failed job=%s: %s", job_id, exc)
        await _finalize_failed(
            job_id=job_id,
            project_id=project_id,
            actor_id=actor_id,
            report_id=report_id,
            error=str(exc)[:1000],
        )


async def _finalize_success(
    *,
    job_id: int,
    project_id: int,
    actor_id: int,
    report_id: int,
    output_path: Path,
    size: int,
    fallback_used: bool,
) -> None:
    async with async_session() as session:
        job = await session.get(ExportJob, job_id)
        if job is None:
            return
        job.status = "succeeded"
        job.finished_at = datetime.now(timezone.utc)
        job.file_path = str(output_path)
        job.file_size = size
        job.fallback_used = fallback_used
        await session.commit()
    await audit_service.log_action(
        action="export.succeeded",
        project_id=project_id,
        report_id=report_id,
        actor_id=actor_id,
        target_type="export",
        target_id=str(job_id),
        after={"file_size": size, "fallback_used": fallback_used},
    )
    await _publish(project_id, job_id, "done", 1.0, "完成")


async def _finalize_failed(
    *,
    job_id: int,
    project_id: int,
    actor_id: int,
    report_id: int,
    error: str,
) -> None:
    async with async_session() as session:
        job = await session.get(ExportJob, job_id)
        if job is None:
            return
        job.status = "failed"
        job.finished_at = datetime.now(timezone.utc)
        job.error = error
        await session.commit()
    await audit_service.log_action(
        action="export.failed",
        project_id=project_id,
        report_id=report_id,
        actor_id=actor_id,
        target_type="export",
        target_id=str(job_id),
        after={"error": error},
    )
    await _publish(project_id, job_id, "failed", 1.0, error[:200])


__all__ = ["run_export"]
