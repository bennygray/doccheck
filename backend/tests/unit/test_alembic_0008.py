"""L1 - alembic 0008_report_export + 新 ORM 模型读写 (C15 report-export)

验证:
- 迁移模块 revision id / down_revision 正确
- AuditLog / ExportJob / ExportTemplate 三新模型 ORM 读写
- AnalysisReport 4 人工复核新字段可读可写
- OverallAnalysis manual_review_json 可读可写
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.session import async_session
from app.models.analysis_report import AnalysisReport
from app.models.audit_log import AUDIT_ACTIONS, AuditLog
from app.models.export_job import EXPORT_JOB_STATUSES, ExportJob
from app.models.export_template import ExportTemplate
from app.models.overall_analysis import OverallAnalysis
from app.models.project import Project
from app.models.user import User


def _load_migration():
    backend_root = Path(__file__).resolve().parents[2]
    mig_file = (
        backend_root / "alembic" / "versions" / "0008_report_export.py"
    )
    assert mig_file.exists(), f"migration file missing: {mig_file}"
    spec = importlib.util.spec_from_file_location("mig_0008", str(mig_file))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_migration_identifiers() -> None:
    mod = _load_migration()
    assert mod.revision == "0008_report_export"
    assert mod.down_revision == "0007_add_doc_meta_template"
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)


def test_audit_actions_enum() -> None:
    # 白名单包含关键 action
    assert "review.report_confirmed" in AUDIT_ACTIONS
    assert "export.requested" in AUDIT_ACTIONS
    assert "export.fallback_to_builtin" in AUDIT_ACTIONS


def test_export_job_statuses_enum() -> None:
    assert EXPORT_JOB_STATUSES == {
        "pending",
        "running",
        "succeeded",
        "failed",
    }


@pytest_asyncio.fixture
async def seed_project():
    async with async_session() as session:
        for M in (
            ExportJob,
            AuditLog,
            ExportTemplate,
            OverallAnalysis,
            AnalysisReport,
            Project,
            User,
        ):
            await session.execute(delete(M))
        user = User(
            username=f"c15_{id(session)}",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        session.add(user)
        await session.flush()
        project = Project(name="P-c15", owner_id=user.id)
        session.add(project)
        await session.flush()
        ar = AnalysisReport(
            project_id=project.id,
            version=1,
            total_score=Decimal("75.00"),
            risk_level="medium",
            llm_conclusion="",
        )
        session.add(ar)
        await session.flush()
        await session.commit()
        yield {"user_id": user.id, "project_id": project.id, "ar_id": ar.id}
    async with async_session() as session:
        for M in (
            ExportJob,
            AuditLog,
            ExportTemplate,
            OverallAnalysis,
            AnalysisReport,
            Project,
            User,
        ):
            await session.execute(delete(M))
        await session.commit()


@pytest.mark.asyncio
async def test_ar_review_fields_default_null(seed_project):
    async with async_session() as session:
        ar = (
            await session.execute(
                select(AnalysisReport).where(
                    AnalysisReport.id == seed_project["ar_id"]
                )
            )
        ).scalar_one()
    assert ar.manual_review_status is None
    assert ar.manual_review_comment is None
    assert ar.reviewer_id is None
    assert ar.reviewed_at is None


@pytest.mark.asyncio
async def test_ar_review_fields_write_read(seed_project):
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        ar = (
            await session.execute(
                select(AnalysisReport).where(
                    AnalysisReport.id == seed_project["ar_id"]
                )
            )
        ).scalar_one()
        ar.manual_review_status = "confirmed"
        ar.manual_review_comment = "证据充分"
        ar.reviewer_id = seed_project["user_id"]
        ar.reviewed_at = now
        await session.commit()

        reloaded = (
            await session.execute(
                select(AnalysisReport).where(
                    AnalysisReport.id == seed_project["ar_id"]
                )
            )
        ).scalar_one()
    assert reloaded.manual_review_status == "confirmed"
    assert reloaded.manual_review_comment == "证据充分"
    assert reloaded.reviewer_id == seed_project["user_id"]
    # 检测原值未变
    assert float(reloaded.total_score) == 75.0
    assert reloaded.risk_level == "medium"


@pytest.mark.asyncio
async def test_oa_manual_review_json(seed_project):
    async with async_session() as session:
        oa = OverallAnalysis(
            project_id=seed_project["project_id"],
            version=1,
            dimension="similarity",
            score=Decimal("80.00"),
            evidence_json={"pairs": []},
            manual_review_json={
                "action": "rejected",
                "comment": "误判",
                "reviewer_id": seed_project["user_id"],
                "at": "2026-04-16T10:00:00Z",
            },
        )
        session.add(oa)
        await session.commit()
        await session.refresh(oa)

        reloaded = (
            await session.execute(
                select(OverallAnalysis).where(OverallAnalysis.id == oa.id)
            )
        ).scalar_one()
    assert reloaded.manual_review_json is not None
    assert reloaded.manual_review_json["action"] == "rejected"
    assert reloaded.manual_review_json["comment"] == "误判"
    # evidence_json 未污染
    assert reloaded.evidence_json == {"pairs": []}


@pytest.mark.asyncio
async def test_audit_log_insert(seed_project):
    async with async_session() as session:
        row = AuditLog(
            project_id=seed_project["project_id"],
            report_id=seed_project["ar_id"],
            actor_id=seed_project["user_id"],
            action="review.report_confirmed",
            target_type="report",
            target_id=str(seed_project["ar_id"]),
            before_json={"status": None, "comment": None},
            after_json={"status": "confirmed", "comment": "ok"},
            ip="127.0.0.1",
            user_agent="pytest",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)

        reloaded = (
            await session.execute(
                select(AuditLog).where(AuditLog.id == row.id)
            )
        ).scalar_one()
    assert reloaded.action == "review.report_confirmed"
    assert reloaded.before_json == {"status": None, "comment": None}
    assert reloaded.after_json == {"status": "confirmed", "comment": "ok"}
    assert reloaded.ip == "127.0.0.1"


@pytest.mark.asyncio
async def test_audit_log_report_id_nullable(seed_project):
    # project 级动作 report_id 可空
    async with async_session() as session:
        row = AuditLog(
            project_id=seed_project["project_id"],
            report_id=None,
            actor_id=seed_project["user_id"],
            action="template.uploaded",
            target_type="template",
            target_id=None,
        )
        session.add(row)
        await session.commit()
    assert row.report_id is None


@pytest.mark.asyncio
async def test_export_job_defaults(seed_project):
    async with async_session() as session:
        job = ExportJob(
            project_id=seed_project["project_id"],
            report_id=seed_project["ar_id"],
            actor_id=seed_project["user_id"],
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        reloaded = (
            await session.execute(
                select(ExportJob).where(ExportJob.id == job.id)
            )
        ).scalar_one()
    assert reloaded.status == "pending"
    assert reloaded.fallback_used is False
    assert reloaded.file_expired is False
    assert reloaded.template_id is None
    assert reloaded.started_at is None
    assert reloaded.finished_at is None


@pytest.mark.asyncio
async def test_export_template_crud(seed_project):
    async with async_session() as session:
        tpl = ExportTemplate(
            owner_id=seed_project["user_id"],
            name="custom",
            file_path="/tmp/custom.docx",
        )
        session.add(tpl)
        await session.commit()
        await session.refresh(tpl)

        reloaded = (
            await session.execute(
                select(ExportTemplate).where(ExportTemplate.id == tpl.id)
            )
        ).scalar_one()
    assert reloaded.name == "custom"
    assert reloaded.file_path == "/tmp/custom.docx"
