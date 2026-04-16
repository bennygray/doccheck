"""L2 - C15 报告视图 API (dimensions / pairs / logs)

扩展 C6 既有 GET /reports/{version} + 新增 3 个子端点。
覆盖场景:
- 总览含 manual_review_* 字段(未复核时 null)
- dimensions 顺序固定为 DIMENSION_WEIGHTS
- dimensions 聚合 OA+PC 产出 best_score / is_ironclad
- dimensions 含 manual_review_json
- pairs 支持 sort_desc + limit
- logs 合并 AgentTask + AuditLog,支持 source 过滤
- 权限 404
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.audit_log import AuditLog
from app.models.export_job import ExportJob
from app.models.export_template import ExportTemplate
from app.models.bidder import Bidder
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.models.user import User
from app.services.detect.judge import DIMENSION_WEIGHTS

from ._c4_helpers import seed_project, seed_user, token_for


@pytest_asyncio.fixture
async def setup(client):
    async with async_session() as s:
        for M in (
            ExportJob,
            ExportTemplate,
            AuditLog,
            AgentTask,
            PairComparison,
            OverallAnalysis,
            AnalysisReport,
            Bidder,
            Project,
            User,
        ):
            await s.execute(delete(M))
        await s.commit()

    owner = await seed_user("c15_view_owner", role="reviewer")
    other = await seed_user("c15_view_other", role="reviewer")
    project = await seed_project(owner_id=owner.id, name="P-c15-view")

    # 建 2 个假 bidder 用于 PC 的 FK
    async with async_session() as s:
        b1 = Bidder(project_id=project.id, name="A公司", parse_status="pending")
        b2 = Bidder(project_id=project.id, name="B公司", parse_status="pending")
        s.add_all([b1, b2])
        await s.commit()
        await s.refresh(b1)
        await s.refresh(b2)
        bidder_a, bidder_b = b1.id, b2.id

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
        # OA 行:text_similarity 有复核标记 + 铁证 (via evidence_json);style 无标记
        s.add(
            OverallAnalysis(
                project_id=project.id,
                version=1,
                dimension="text_similarity",
                score=Decimal("60.00"),
                evidence_json={
                    "summary": "文本高度相似",
                    "has_iron_evidence": True,
                },
                manual_review_json={
                    "action": "confirmed",
                    "comment": "ok",
                    "reviewer_id": owner.id,
                    "at": "2026-04-16T10:00:00Z",
                },
            )
        )
        s.add(
            OverallAnalysis(
                project_id=project.id,
                version=1,
                dimension="style",
                score=Decimal("30.00"),
                evidence_json={"summary": "风格差异大"},
            )
        )
        # PC 行(2 条):dimension=metadata_author 高分铁证;dimension=style 中分
        s.add(
            PairComparison(
                project_id=project.id,
                version=1,
                dimension="metadata_author",
                bidder_a_id=bidder_a,
                bidder_b_id=bidder_b,
                score=Decimal("90.00"),
                is_ironclad=True,
                evidence_json={"summary": "同一 author"},
            )
        )
        s.add(
            PairComparison(
                project_id=project.id,
                version=1,
                dimension="style",
                bidder_a_id=bidder_a,
                bidder_b_id=bidder_b,
                score=Decimal("50.00"),
                is_ironclad=False,
                evidence_json={"summary": "pair 风格中等"},
            )
        )
        # AgentTask 1 条:pair 型需要 bidder_a_id / bidder_b_id(CheckConstraint 约束)
        s.add(
            AgentTask(
                project_id=project.id,
                version=1,
                agent_name="text_similarity",
                agent_type="pair",
                pair_bidder_a_id=bidder_a,
                pair_bidder_b_id=bidder_b,
                status="succeeded",
                score=Decimal("60.00"),
                summary="执行完成",
            )
        )
        # AuditLog 1 条
        s.add(
            AuditLog(
                project_id=project.id,
                report_id=ar.id,
                actor_id=owner.id,
                action="review.report_confirmed",
                target_type="report",
                target_id=str(ar.id),
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


# ============================================================ GET /reports/{version}


@pytest.mark.asyncio
async def test_get_report_with_review_fields_null(setup):
    resp = await setup["client"].get(
        f"/api/projects/{setup['project_id']}/reports/1",
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # C15 新字段存在且为 null(未对 AR 做复核)
    assert body["manual_review_status"] is None
    assert body["manual_review_comment"] is None
    assert body["reviewer_id"] is None
    assert body["reviewed_at"] is None


@pytest.mark.asyncio
async def test_get_report_no_permission_404(setup):
    resp = await setup["client"].get(
        f"/api/projects/{setup['project_id']}/reports/1",
        headers={"Authorization": f"Bearer {token_for(setup['other'])}"},
    )
    assert resp.status_code == 404


# ============================================================ dimensions


@pytest.mark.asyncio
async def test_dimensions_order_and_best_score(setup):
    resp = await setup["client"].get(
        f"/api/projects/{setup['project_id']}/reports/1/dimensions",
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 200
    dims = resp.json()["dimensions"]
    # 长度 = 11,顺序 = DIMENSION_WEIGHTS
    assert len(dims) == len(DIMENSION_WEIGHTS)
    assert [d["dimension"] for d in dims] == list(DIMENSION_WEIGHTS.keys())

    by_dim = {d["dimension"]: d for d in dims}
    # text_similarity: OA.score=60, 有 has_iron_evidence,有复核
    assert by_dim["text_similarity"]["best_score"] == 60.0
    assert by_dim["text_similarity"]["is_ironclad"] is True
    assert by_dim["text_similarity"]["evidence_summary"] == "文本高度相似"
    assert by_dim["text_similarity"]["manual_review_json"]["action"] == "confirmed"
    # metadata_author: PC.score=90 iron;无 OA
    assert by_dim["metadata_author"]["best_score"] == 90.0
    assert by_dim["metadata_author"]["is_ironclad"] is True
    # style: OA.score=30, PC.score=50 → 取 50;不铁证
    assert by_dim["style"]["best_score"] == 50.0
    assert by_dim["style"]["is_ironclad"] is False
    # 未 seed 的维度 best_score 为 0
    assert by_dim["price_anomaly"]["best_score"] == 0.0
    assert by_dim["price_anomaly"]["is_ironclad"] is False
    assert by_dim["price_anomaly"]["manual_review_json"] is None


# ============================================================ pairs


@pytest.mark.asyncio
async def test_pairs_sort_desc(setup):
    resp = await setup["client"].get(
        f"/api/projects/{setup['project_id']}/reports/1/pairs",
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    # 第一个 score 应更高
    assert items[0]["score"] >= items[1]["score"]
    assert items[0]["score"] == 90.0
    assert items[0]["is_ironclad"] is True


@pytest.mark.asyncio
async def test_pairs_limit(setup):
    resp = await setup["client"].get(
        f"/api/projects/{setup['project_id']}/reports/1/pairs?limit=1",
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1


# ============================================================ logs


@pytest.mark.asyncio
async def test_logs_merge_all(setup):
    resp = await setup["client"].get(
        f"/api/projects/{setup['project_id']}/reports/1/logs",
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    sources = {i["source"] for i in items}
    assert sources == {"agent_task", "audit_log"}


@pytest.mark.asyncio
async def test_logs_filter_audit(setup):
    resp = await setup["client"].get(
        f"/api/projects/{setup['project_id']}/reports/1/logs?source=audit_log",
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["source"] == "audit_log"
    assert items[0]["payload"]["action"] == "review.report_confirmed"


@pytest.mark.asyncio
async def test_logs_filter_agent_task(setup):
    resp = await setup["client"].get(
        f"/api/projects/{setup['project_id']}/reports/1/logs?source=agent_task",
        headers={"Authorization": f"Bearer {token_for(setup['owner'])}"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["source"] == "agent_task"
    assert items[0]["payload"]["agent_name"] == "text_similarity"


@pytest.mark.asyncio
async def test_dimensions_no_permission_404(setup):
    resp = await setup["client"].get(
        f"/api/projects/{setup['project_id']}/reports/1/dimensions",
        headers={"Authorization": f"Bearer {token_for(setup['other'])}"},
    )
    assert resp.status_code == 404
