"""L2 - AnalysisStatusResponse.report_ready field (honest-detection-results N4).

覆盖:
(a) 从未检测过的项目 → report_ready=false
(b) 启动检测但 AnalysisReport 未写入 → report_ready=false
(c) AnalysisReport 已写入 → report_ready=true
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.db.session import async_session
from app.models.analysis_report import AnalysisReport
from app.models.bidder import Bidder
from app.models.project import Project
from app.models.user import User

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _disable_detect(monkeypatch):
    monkeypatch.setenv("INFRA_DISABLE_DETECT", "1")


async def _seed(owner_id: int, n: int = 2) -> int:
    async with async_session() as s:
        p = Project(name="p_rr", status="ready", owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        for i in range(n):
            s.add(
                Bidder(
                    name=f"B{i}",
                    project_id=p.id,
                    parse_status="identified",
                )
            )
        await s.commit()
        return p.id


async def test_report_ready_false_before_start(
    seeded_reviewer: User, reviewer_token, auth_client
) -> None:
    """(a) 从未检测过 → report_ready=false"""
    pid = await _seed(seeded_reviewer.id)
    client = await auth_client(reviewer_token)
    resp = await client.get(f"/api/projects/{pid}/analysis/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] is None
    assert body["report_ready"] is False


async def test_report_ready_false_after_start_before_judge(
    seeded_reviewer: User, reviewer_token, auth_client
) -> None:
    """(b) 启动检测但 AnalysisReport 未写入(INFRA_DISABLE_DETECT=1 模拟) → report_ready=false"""
    pid = await _seed(seeded_reviewer.id)
    client = await auth_client(reviewer_token)
    await client.post(f"/api/projects/{pid}/analysis/start")

    resp = await client.get(f"/api/projects/{pid}/analysis/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 1
    assert body["report_ready"] is False  # judge 未跑 → 无 AnalysisReport 行


async def test_report_ready_true_when_report_inserted(
    seeded_reviewer: User, reviewer_token, auth_client
) -> None:
    """(c) 手工插入 AnalysisReport 行 → report_ready=true"""
    pid = await _seed(seeded_reviewer.id)
    client = await auth_client(reviewer_token)
    await client.post(f"/api/projects/{pid}/analysis/start")

    # 手工写入 AnalysisReport 模拟 judge 完成
    async with async_session() as s:
        s.add(
            AnalysisReport(
                project_id=pid,
                version=1,
                total_score=Decimal("0"),
                risk_level="low",
                llm_conclusion="test",
            )
        )
        await s.commit()

    resp = await client.get(f"/api/projects/{pid}/analysis/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 1
    assert body["report_ready"] is True
    assert body["latest_report"] is not None  # 也应同时有 latest_report
