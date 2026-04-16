"""L2 - C15 导出 API + worker 端到端 (spec report-export)

覆盖场景:
- S1 默认模板全链路:触发 → worker 完成 → 文件落盘 → 下载 200
- S2 用户模板坏 → fallback 内置 → audit.export.fallback_to_builtin → 仍下载成功
- S3 内置模板渲染失败 → job FAILED + audit.export.failed + 409 下载
- S6 文件过期 → 410 下载
- 权限 404:他人 project 不可触发,不可下载

环境约定:C15_DISABLE_EXPORT_WORKER=1 禁用 auto worker,测试内手工调 run_export。
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.audit_log import AuditLog
from app.models.bidder import Bidder
from app.models.export_job import ExportJob
from app.models.export_template import ExportTemplate
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.models.user import User
from app.services.export.worker import run_export

from ._c4_helpers import seed_project, seed_user, token_for


@pytest.fixture(autouse=True)
def _disable_auto_worker(monkeypatch):
    """测试默认禁用 auto worker;各测试内显式调 run_export。"""
    monkeypatch.setenv("C15_DISABLE_EXPORT_WORKER", "1")


@pytest_asyncio.fixture
async def setup(client):
    async with async_session() as s:
        for M in (
            ExportJob,
            ExportTemplate,
            AuditLog,
            AgentTask,  # 子表先删,避免 FK 违约
            PairComparison,
            OverallAnalysis,
            AnalysisReport,
            Bidder,
            Project,
            User,
        ):
            await s.execute(delete(M))
        await s.commit()

    owner = await seed_user("c15_exp_owner", role="reviewer")
    other = await seed_user("c15_exp_other", role="reviewer")
    project = await seed_project(owner_id=owner.id, name="P-c15-export")

    async with async_session() as s:
        ar = AnalysisReport(
            project_id=project.id,
            version=1,
            total_score=Decimal("72.50"),
            risk_level="medium",
            llm_conclusion="",
        )
        s.add(ar)
        await s.flush()
        # 两个 OA 行让渲染有点内容
        s.add(
            OverallAnalysis(
                project_id=project.id,
                version=1,
                dimension="text_similarity",
                score=Decimal("60.00"),
                evidence_json={"summary": "相似度高"},
            )
        )
        await s.commit()
        await s.refresh(ar)

    return {
        "client": client,
        "owner": owner,
        "other": other,
        "project_id": project.id,
        "ar_id": ar.id,
        "version": 1,
    }


# ============================================================ S1 默认模板全链路


@pytest.mark.asyncio
async def test_s1_default_template_full_flow(setup, tmp_path, monkeypatch):
    # 将导出目录指向 tmp_path(worker 通过 settings.upload_dir 解析)
    from app.services.export import worker as worker_mod

    monkeypatch.setattr(
        worker_mod, "_export_dir", lambda: tmp_path / "exports"
    )

    # 1) 触发
    resp = await setup["client"].post(
        f"/api/projects/{setup['project_id']}/reports/1/export",
        json={},
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # audit_log 有 export.requested
    async with async_session() as s:
        rows = (
            await s.execute(
                select(AuditLog).where(AuditLog.action == "export.requested")
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].target_id == str(job_id)

    # 2) 手工跑 worker
    await run_export(job_id)

    # 3) 检查 job
    async with async_session() as s:
        job = await s.get(ExportJob, job_id)
    assert job.status == "succeeded"
    assert job.fallback_used is False
    assert job.file_path is not None
    assert Path(job.file_path).exists()
    assert job.file_size and job.file_size > 0

    # audit.export.succeeded
    async with async_session() as s:
        rows = (
            await s.execute(
                select(AuditLog).where(AuditLog.action == "export.succeeded")
            )
        ).scalars().all()
    assert len(rows) == 1

    # 4) 下载
    resp = await setup["client"].get(
        f"/api/exports/{job_id}/download",
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    assert b"PK" in resp.content[:4]  # docx = zip
    # audit.export.downloaded
    async with async_session() as s:
        rows = (
            await s.execute(
                select(AuditLog).where(AuditLog.action == "export.downloaded")
            )
        ).scalars().all()
    assert len(rows) == 1


# ============================================================ S2 用户模板坏 → fallback


@pytest.mark.asyncio
async def test_s2_user_template_broken_fallback(setup, tmp_path, monkeypatch):
    from app.services.export import worker as worker_mod

    monkeypatch.setattr(
        worker_mod, "_export_dir", lambda: tmp_path / "exports"
    )

    # 建一个指向不存在文件的模板
    bad_template_path = tmp_path / "nonexistent.docx"
    async with async_session() as s:
        tpl = ExportTemplate(
            owner_id=setup["owner"].id,
            name="bad",
            file_path=str(bad_template_path),
        )
        s.add(tpl)
        await s.commit()
        await s.refresh(tpl)
        tpl_id = tpl.id

    # 触发导出指定坏模板
    resp = await setup["client"].post(
        f"/api/projects/{setup['project_id']}/reports/1/export",
        json={"template_id": tpl_id},
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    await run_export(job_id)

    async with async_session() as s:
        job = await s.get(ExportJob, job_id)
    # 应该仍 succeeded,fallback_used=true
    assert job.status == "succeeded"
    assert job.fallback_used is True
    assert job.file_path and Path(job.file_path).exists()

    # audit 记 fallback_to_builtin + succeeded
    async with async_session() as s:
        rows = (
            await s.execute(
                select(AuditLog).order_by(AuditLog.id.asc())
            )
        ).scalars().all()
    actions = [r.action for r in rows]
    assert "export.requested" in actions
    assert "export.fallback_to_builtin" in actions
    assert "export.succeeded" in actions
    # before/after 快照正确
    fb = next(r for r in rows if r.action == "export.fallback_to_builtin")
    assert fb.before_json == {"template_id": tpl_id}
    assert fb.after_json == {"fallback_template": "default.docx"}


# ============================================================ S3 内置渲染失败


@pytest.mark.asyncio
async def test_s3_builtin_render_failure_marks_failed(
    setup, tmp_path, monkeypatch
):
    from app.services.export import worker as worker_mod

    monkeypatch.setattr(
        worker_mod, "_export_dir", lambda: tmp_path / "exports"
    )

    # patch render_to_file 直接抛异常
    def _boom(*args, **kwargs):
        raise RuntimeError("render crash")

    monkeypatch.setattr(worker_mod, "render_to_file", _boom)

    resp = await setup["client"].post(
        f"/api/projects/{setup['project_id']}/reports/1/export",
        json={},
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    job_id = resp.json()["job_id"]
    await run_export(job_id)

    async with async_session() as s:
        job = await s.get(ExportJob, job_id)
    assert job.status == "failed"
    assert job.error and "render crash" in job.error

    # audit.export.failed
    async with async_session() as s:
        rows = (
            await s.execute(
                select(AuditLog).where(AuditLog.action == "export.failed")
            )
        ).scalars().all()
    assert len(rows) == 1

    # 下载返 409
    resp = await setup["client"].get(
        f"/api/exports/{job_id}/download",
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 409


# ============================================================ S6 文件过期 → 410


@pytest.mark.asyncio
async def test_s6_expired_file_returns_410(setup, tmp_path, monkeypatch):
    from app.services.export import worker as worker_mod

    monkeypatch.setattr(
        worker_mod, "_export_dir", lambda: tmp_path / "exports"
    )

    resp = await setup["client"].post(
        f"/api/projects/{setup['project_id']}/reports/1/export",
        json={},
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    job_id = resp.json()["job_id"]
    await run_export(job_id)

    # 手工标记过期
    async with async_session() as s:
        job = await s.get(ExportJob, job_id)
        job.file_expired = True
        await s.commit()

    resp = await setup["client"].get(
        f"/api/exports/{job_id}/download",
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 410
    body = resp.json()
    assert body["detail"]["error"] == "file_expired"


# ============================================================ 权限 404


@pytest.mark.asyncio
async def test_export_no_permission_to_start(setup):
    resp = await setup["client"].post(
        f"/api/projects/{setup['project_id']}/reports/1/export",
        json={},
        headers={"Authorization": f"Bearer {token_for(setup['other'])}"},
    )
    assert resp.status_code == 404
    # 无 job 创建
    async with async_session() as s:
        rows = (await s.execute(select(ExportJob))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_download_no_permission(setup, tmp_path, monkeypatch):
    from app.services.export import worker as worker_mod

    monkeypatch.setattr(
        worker_mod, "_export_dir", lambda: tmp_path / "exports"
    )

    resp = await setup["client"].post(
        f"/api/projects/{setup['project_id']}/reports/1/export",
        json={},
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    job_id = resp.json()["job_id"]
    await run_export(job_id)

    # other 尝试下载 → 404
    resp = await setup["client"].get(
        f"/api/exports/{job_id}/download",
        headers={"Authorization": f"Bearer {token_for(setup['other'])}"},
    )
    assert resp.status_code == 404
