"""L2: GET /api/projects/{pid}/reports/{version} (C6 §11.6)"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _seed_report(
    owner_id: int,
    *,
    with_ironclad_pair: bool = False,
) -> int:
    async with async_session() as s:
        p = Project(name="p", status="completed", owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)

        # 建一个简单报告 + 1 个 pair + 1 个 agent_task
        if with_ironclad_pair:
            pc = PairComparison(
                project_id=p.id,
                version=1,
                bidder_a_id=None,  # FK 允许?需要真实 bidder_id
                bidder_b_id=None,
                dimension="price_consistency",
                score=Decimal("95.0"),
                is_ironclad=True,
            )
        # 为了避免 FK 违反,直接用 SQL 写也 OK,这里简化:不建 pair_comparisons,只建 AnalysisReport
        # agent_task 行
        at = AgentTask(
            project_id=p.id,
            version=1,
            agent_name="text_similarity",
            agent_type="pair",
            pair_bidder_a_id=None,  # 会被 PG CHECK 拒绝;简化:global 型
            pair_bidder_b_id=None,
            status="succeeded",
            score=Decimal("42.5"),
            summary="dummy",
        )
        # 改 global 型规避 CHECK
        at.agent_type = "global"
        at.agent_name = "style"

        ar = AnalysisReport(
            project_id=p.id,
            version=1,
            total_score=Decimal("67.5"),
            risk_level="medium",
            llm_conclusion="",
        )

        s.add(at)
        s.add(ar)
        await s.commit()
        return p.id


async def test_report_existing_200(
    seeded_reviewer: User, reviewer_token, auth_client
):
    pid = await _seed_report(seeded_reviewer.id)
    client = await auth_client(reviewer_token)
    resp = await client.get(f"/api/projects/{pid}/reports/1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == 1
    assert body["risk_level"] == "medium"
    assert body["llm_conclusion"] == ""
    # 13 维度(C12 新增 price_anomaly + fix-bug-triple price_total_match/price_overshoot)
    assert len(body["dimensions"]) == 13
    dim_names = {d["dimension"] for d in body["dimensions"]}
    assert "text_similarity" in dim_names
    assert "error_consistency" in dim_names


async def test_report_missing_404(
    seeded_reviewer: User, reviewer_token, auth_client
):
    async with async_session() as s:
        p = Project(
            name="empty", status="ready", owner_id=seeded_reviewer.id
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        pid = p.id

    client = await auth_client(reviewer_token)
    resp = await client.get(f"/api/projects/{pid}/reports/99")
    assert resp.status_code == 404


async def test_report_non_owner_404(
    seeded_reviewer: User, reviewer_token, auth_client
):
    from app.services.auth.password import hash_password

    async with async_session() as s:
        u = User(
            username="other_r",
            password_hash=hash_password("pw1234567"),
            role="reviewer",
            is_active=True,
            must_change_password=False,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        pid = await _seed_report(u.id)

    client = await auth_client(reviewer_token)
    resp = await client.get(f"/api/projects/{pid}/reports/1")
    assert resp.status_code == 404
