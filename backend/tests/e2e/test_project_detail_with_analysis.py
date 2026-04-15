"""L2: GET /api/projects/{id} response analysis 字段 (C6 §11.10)

覆盖 project-mgmt MODIFIED 的 "C6 analysis 字段" 相关 Scenario。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.bidder import Bidder
from app.models.project import Project
from app.models.user import User

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _disable_detect(monkeypatch):
    monkeypatch.setenv("INFRA_DISABLE_DETECT", "1")


async def test_detail_analysis_null_when_never_detected(
    seeded_reviewer: User, reviewer_token, auth_client
):
    async with async_session() as s:
        p = Project(
            name="p", status="ready", owner_id=seeded_reviewer.id
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        pid = p.id

    client = await auth_client(reviewer_token)
    resp = await client.get(f"/api/projects/{pid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] is None


async def test_detail_analysis_populated_after_start(
    seeded_reviewer: User, reviewer_token, auth_client
):
    async with async_session() as s:
        p = Project(name="p", status="ready", owner_id=seeded_reviewer.id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        for i in range(2):
            s.add(
                Bidder(
                    name=f"B{i}",
                    project_id=p.id,
                    parse_status="identified",
                )
            )
        await s.commit()
        pid = p.id

    client = await auth_client(reviewer_token)
    await client.post(f"/api/projects/{pid}/analysis/start")

    resp = await client.get(f"/api/projects/{pid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] is not None
    assert body["analysis"]["current_version"] == 1
    assert body["analysis"]["project_status"] == "analyzing"
    assert body["analysis"]["agent_task_count"] == 11
    assert body["analysis"]["latest_report"] is None


async def test_detail_analysis_with_latest_report(
    seeded_reviewer: User, reviewer_token, auth_client
):
    async with async_session() as s:
        p = Project(
            name="p",
            status="completed",
            risk_level="high",
            owner_id=seeded_reviewer.id,
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        # 手动插 AgentTask + AnalysisReport
        at = AgentTask(
            project_id=p.id,
            version=1,
            agent_name="style",
            agent_type="global",
            status="succeeded",
        )
        ar = AnalysisReport(
            project_id=p.id,
            version=1,
            total_score=Decimal("88.0"),
            risk_level="high",
            llm_conclusion="",
        )
        s.add(at)
        s.add(ar)
        await s.commit()
        pid = p.id

    client = await auth_client(reviewer_token)
    resp = await client.get(f"/api/projects/{pid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"]["latest_report"] is not None
    assert body["analysis"]["latest_report"]["version"] == 1
    assert body["analysis"]["latest_report"]["risk_level"] == "high"
    assert body["analysis"]["latest_report"]["total_score"] == 88.0
