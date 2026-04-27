"""L2: POST /api/projects/{pid}/analysis/start (C6 §11.3)

覆盖 spec "启动检测 API" + "前置校验" + "幂等 409" 的 Scenario。
用 INFRA_DISABLE_DETECT=1 避免真实调度(engine.run_detection 跳过)。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.bidder import Bidder
from app.models.project import Project
from app.models.user import User

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _disable_detect(monkeypatch):
    monkeypatch.setenv("INFRA_DISABLE_DETECT", "1")


async def _seed_project_with_bidders(
    owner_id: int,
    n_bidders: int = 2,
    project_status: str = "ready",
    bidder_status: str = "identified",
) -> tuple[int, list[int]]:
    async with async_session() as s:
        p = Project(name="p", status=project_status, owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        bids = []
        for i in range(n_bidders):
            b = Bidder(
                name=f"B{i}",
                project_id=p.id,
                parse_status=bidder_status,
            )
            s.add(b)
        await s.commit()
        result = (
            await s.execute(select(Bidder).where(Bidder.project_id == p.id))
        ).scalars().all()
        return p.id, [b.id for b in result]


async def test_start_2_bidders_201_11_tasks(
    seeded_reviewer: User, reviewer_token, auth_client
):
    """2 bidders → 1 pair × 7 + 4 global = 11 AgentTask (C12 后)。"""
    pid, _ = await _seed_project_with_bidders(seeded_reviewer.id, n_bidders=2)
    client = await auth_client(reviewer_token)
    resp = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["version"] == 1
    assert body["agent_task_count"] == 13  # fix-bug-triple +2 global

    async with async_session() as s:
        rows = list(
            (
                await s.execute(select(AgentTask).where(AgentTask.project_id == pid))
            ).scalars().all()
        )
        assert len(rows) == 13  # fix-bug-triple +2 global
        # 状态全 pending(INFRA_DISABLE_DETECT=1 跳过自动调度)
        assert all(r.status == "pending" for r in rows)
        # project 进 analyzing
        project = await s.get(Project, pid)
        assert project.status == "analyzing"


async def test_start_3_bidders_25_tasks(
    seeded_reviewer: User, reviewer_token, auth_client
):
    """3 bidders → C(3,2) × 7 + 4 global = 25 (C12 后)。"""
    pid, _ = await _seed_project_with_bidders(seeded_reviewer.id, n_bidders=3)
    client = await auth_client(reviewer_token)
    resp = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp.status_code == 201
    assert resp.json()["agent_task_count"] == 27  # fix-bug-triple +2 global × 3 bidder = +2


async def test_start_1_bidder_400(
    seeded_reviewer: User, reviewer_token, auth_client
):
    pid, _ = await _seed_project_with_bidders(seeded_reviewer.id, n_bidders=1)
    client = await auth_client(reviewer_token)
    resp = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp.status_code == 400
    assert "2个投标人" in resp.json()["detail"]


async def test_start_non_terminal_bidder_400(
    seeded_reviewer: User, reviewer_token, auth_client
):
    pid, _ = await _seed_project_with_bidders(
        seeded_reviewer.id, n_bidders=2, bidder_status="identifying"
    )
    client = await auth_client(reviewer_token)
    resp = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp.status_code == 400
    assert "解析完成" in resp.json()["detail"]


async def test_start_draft_project_400(
    seeded_reviewer: User, reviewer_token, auth_client
):
    pid, _ = await _seed_project_with_bidders(
        seeded_reviewer.id, n_bidders=2, project_status="draft"
    )
    client = await auth_client(reviewer_token)
    resp = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp.status_code == 400
    assert "未就绪" in resp.json()["detail"]


async def test_start_analyzing_project_409(
    seeded_reviewer: User, reviewer_token, auth_client
):
    pid, _ = await _seed_project_with_bidders(seeded_reviewer.id, n_bidders=2)
    client = await auth_client(reviewer_token)
    resp1 = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp1.status_code == 201
    # 再次启动 → 409
    resp2 = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp2.status_code == 409
    detail = resp2.json()["detail"]
    # detail 为 dict {current_version, started_at, message}
    assert detail["current_version"] == 1


async def test_start_version_increments_after_failed(
    seeded_reviewer: User, reviewer_token, auth_client
):
    """失败的 version 占位不复用:v=1 全 failed 后 project 回 ready,重启应 v=2。"""
    pid, _ = await _seed_project_with_bidders(seeded_reviewer.id, n_bidders=2)
    client = await auth_client(reviewer_token)
    resp1 = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp1.status_code == 201
    assert resp1.json()["version"] == 1

    # 标所有 AgentTask 为 failed + project 回 ready
    async with async_session() as s:
        rows = (
            await s.execute(select(AgentTask).where(AgentTask.project_id == pid))
        ).scalars().all()
        for r in rows:
            r.status = "failed"
        project = await s.get(Project, pid)
        project.status = "ready"
        await s.commit()

    resp2 = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp2.status_code == 201
    assert resp2.json()["version"] == 2


async def test_start_other_owner_404(
    seeded_reviewer: User, reviewer_token, auth_client
):
    """owner B 的项目,reviewer A 启动应 404。"""
    # 建另一个 user B 的项目
    from app.services.auth.password import hash_password

    async with async_session() as s:
        u_b = User(
            username="b_user",
            password_hash=hash_password("pw1234567"),
            role="reviewer",
            is_active=True,
            must_change_password=False,
        )
        s.add(u_b)
        await s.commit()
        await s.refresh(u_b)
        pid, _ = await _seed_project_with_bidders(u_b.id, n_bidders=2)

    client = await auth_client(reviewer_token)
    resp = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp.status_code == 404


async def test_start_admin_can_start_any(
    seeded_admin: User, admin_token, auth_client
):
    """admin 可启动任意 reviewer 的项目。"""
    from app.services.auth.password import hash_password

    async with async_session() as s:
        u = User(
            username="reviewer_for_admin_test",
            password_hash=hash_password("pw1234567"),
            role="reviewer",
            is_active=True,
            must_change_password=False,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        pid, _ = await _seed_project_with_bidders(u.id, n_bidders=2)

    client = await auth_client(admin_token)
    resp = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp.status_code == 201


async def test_start_unauth_401(auth_client):
    """无 token → 401。"""
    client = await auth_client(None)
    resp = await client.post("/api/projects/1/analysis/start")
    assert resp.status_code == 401
