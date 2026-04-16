"""L2 - 人工复核 API E2E (C15 report-export, spec manual-review)

覆盖场景:
- 整报告级:首次复核 / 重复复核覆盖 / 非法 status 400 / 无权限 404 / 检测原值 invariance
- 维度级:正常写入 / 非法 action 400 / 未知 dim 404 / 维度级不影响整报告级
- audit_log 记录正确 before/after
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.session import async_session
from app.models.analysis_report import AnalysisReport
from app.models.audit_log import AuditLog
from app.models.export_job import ExportJob
from app.models.export_template import ExportTemplate
from app.models.overall_analysis import OverallAnalysis
from app.models.project import Project
from app.models.user import User

from ._c4_helpers import seed_project, seed_user, token_for


@pytest_asyncio.fixture
async def setup(client):
    # 清理(顺序重要:先子后父,子表先清)
    async with async_session() as s:
        for M in (
            ExportJob,
            ExportTemplate,
            AuditLog,
            OverallAnalysis,
            AnalysisReport,
            Project,
            User,
        ):
            await s.execute(delete(M))
        await s.commit()

    owner = await seed_user("c15_reviewer_owner", role="reviewer")
    other = await seed_user("c15_reviewer_other", role="reviewer")
    admin = await seed_user("c15_admin", role="admin")
    project = await seed_project(owner_id=owner.id, name="P-c15")

    # 建一个 AR + 3 条 OA
    async with async_session() as s:
        ar = AnalysisReport(
            project_id=project.id,
            version=1,
            total_score=Decimal("80.00"),
            risk_level="high",
            llm_conclusion="existing judgment",
        )
        s.add(ar)
        await s.flush()
        for dim in ("text_similarity", "metadata_author", "style"):
            s.add(
                OverallAnalysis(
                    project_id=project.id,
                    version=1,
                    dimension=dim,
                    score=Decimal("50.00"),
                    evidence_json={"k": "v"},
                )
            )
        await s.commit()
        await s.refresh(ar)

    return {
        "client": client,
        "owner": owner,
        "other": other,
        "admin": admin,
        "project_id": project.id,
        "ar_id": ar.id,
        "version": 1,
    }


# ============================================================ 整报告级


@pytest.mark.asyncio
async def test_review_first_time_confirmed(setup):
    client = setup["client"]
    resp = await client.post(
        f"/api/projects/{setup['project_id']}/reports/{setup['version']}/review",
        json={"status": "confirmed", "comment": "证据充分"},
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["manual_review_status"] == "confirmed"
    assert body["manual_review_comment"] == "证据充分"
    assert body["reviewer_id"] == setup["owner"].id

    # 检测原值不变
    async with async_session() as s:
        ar = (
            await s.execute(
                select(AnalysisReport).where(
                    AnalysisReport.id == setup["ar_id"]
                )
            )
        ).scalar_one()
    assert float(ar.total_score) == 80.0
    assert ar.risk_level == "high"
    assert ar.llm_conclusion == "existing judgment"
    assert ar.manual_review_status == "confirmed"
    assert ar.reviewer_id == setup["owner"].id
    assert ar.reviewed_at is not None

    # audit_log 有一条 review.report_confirmed
    async with async_session() as s:
        rows = (await s.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    r = rows[0]
    assert r.action == "review.report_confirmed"
    assert r.before_json == {"status": None, "comment": None}
    assert r.after_json == {"status": "confirmed", "comment": "证据充分"}
    assert r.target_type == "report"
    assert r.target_id == str(setup["ar_id"])


@pytest.mark.asyncio
async def test_review_overwrite(setup):
    client = setup["client"]
    headers = {"Authorization": f"Bearer {token_for(setup['owner'])}"}
    # 第一次
    await client.post(
        f"/api/projects/{setup['project_id']}/reports/1/review",
        json={"status": "confirmed", "comment": "first"},
        headers=headers,
    )
    # 第二次覆盖为 downgraded
    resp = await client.post(
        f"/api/projects/{setup['project_id']}/reports/1/review",
        json={"status": "downgraded", "comment": "重新评估"},
        headers=headers,
    )
    assert resp.status_code == 200
    async with async_session() as s:
        ar = (
            await s.execute(
                select(AnalysisReport).where(
                    AnalysisReport.id == setup["ar_id"]
                )
            )
        ).scalar_one()
    assert ar.manual_review_status == "downgraded"
    # total_score 依然不变
    assert float(ar.total_score) == 80.0

    # audit_log 第二条 before={status:confirmed, comment:first}
    async with async_session() as s:
        rows = (
            await s.execute(
                select(AuditLog).order_by(AuditLog.id.asc())
            )
        ).scalars().all()
    assert len(rows) == 2
    assert rows[1].action == "review.report_downgraded"
    assert rows[1].before_json == {"status": "confirmed", "comment": "first"}
    assert rows[1].after_json == {"status": "downgraded", "comment": "重新评估"}


@pytest.mark.asyncio
async def test_review_invalid_status_400(setup):
    client = setup["client"]
    resp = await client.post(
        f"/api/projects/{setup['project_id']}/reports/1/review",
        json={"status": "something_else"},
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 400
    # AR 未被修改
    async with async_session() as s:
        ar = (
            await s.execute(
                select(AnalysisReport).where(
                    AnalysisReport.id == setup["ar_id"]
                )
            )
        ).scalar_one()
    assert ar.manual_review_status is None


@pytest.mark.asyncio
async def test_review_no_permission_404(setup):
    client = setup["client"]
    resp = await client.post(
        f"/api/projects/{setup['project_id']}/reports/1/review",
        json={"status": "confirmed"},
        headers={"Authorization": f"Bearer {token_for(setup['other'])}"},
    )
    assert resp.status_code == 404
    async with async_session() as s:
        ar = (
            await s.execute(
                select(AnalysisReport).where(
                    AnalysisReport.id == setup["ar_id"]
                )
            )
        ).scalar_one()
    assert ar.manual_review_status is None
    # 无 audit_log
    async with async_session() as s:
        rows = (await s.execute(select(AuditLog))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_review_admin_can_review_any(setup):
    client = setup["client"]
    resp = await client.post(
        f"/api/projects/{setup['project_id']}/reports/1/review",
        json={"status": "rejected"},
        headers={"Authorization": f"Bearer {token_for(setup['admin'])}"},
    )
    assert resp.status_code == 200


# ============================================================ 维度级


@pytest.mark.asyncio
async def test_dimension_review_success(setup):
    client = setup["client"]
    resp = await client.post(
        f"/api/projects/{setup['project_id']}/reports/1/dimensions/text_similarity/review",
        json={"action": "rejected", "comment": "误判"},
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dimension"] == "text_similarity"
    assert body["manual_review_json"]["action"] == "rejected"
    assert body["manual_review_json"]["comment"] == "误判"
    assert body["manual_review_json"]["reviewer_id"] == setup["owner"].id

    # OA.evidence_json 未被污染
    async with async_session() as s:
        oa = (
            await s.execute(
                select(OverallAnalysis).where(
                    OverallAnalysis.project_id == setup["project_id"],
                    OverallAnalysis.version == 1,
                    OverallAnalysis.dimension == "text_similarity",
                )
            )
        ).scalar_one()
    assert oa.evidence_json == {"k": "v"}
    assert float(oa.score) == 50.0
    assert oa.manual_review_json["action"] == "rejected"

    # audit_log
    async with async_session() as s:
        rows = (await s.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].action == "review.dimension_marked"
    assert rows[0].target_type == "report_dimension"
    assert rows[0].target_id == "text_similarity"


@pytest.mark.asyncio
async def test_dimension_review_invalid_action_400(setup):
    client = setup["client"]
    resp = await client.post(
        f"/api/projects/{setup['project_id']}/reports/1/dimensions/text_similarity/review",
        json={"action": "bogus"},
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_dimension_review_unknown_dim_404(setup):
    client = setup["client"]
    resp = await client.post(
        f"/api/projects/{setup['project_id']}/reports/1/dimensions/nope_dim/review",
        json={"action": "note"},
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dimension_review_no_oa_row_404(setup):
    """price_anomaly 维度合法但 setup 没 seed 该 OA 行,应返 404。"""
    client = setup["client"]
    resp = await client.post(
        f"/api/projects/{setup['project_id']}/reports/1/dimensions/price_anomaly/review",
        json={"action": "confirmed"},
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dimension_review_does_not_touch_ar(setup):
    client = setup["client"]
    await client.post(
        f"/api/projects/{setup['project_id']}/reports/1/dimensions/text_similarity/review",
        json={"action": "rejected"},
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    async with async_session() as s:
        ar = (
            await s.execute(
                select(AnalysisReport).where(
                    AnalysisReport.id == setup["ar_id"]
                )
            )
        ).scalar_one()
    # AR.manual_review_status 仍然 null
    assert ar.manual_review_status is None
