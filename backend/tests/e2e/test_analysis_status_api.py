"""L2: GET /api/projects/{pid}/analysis/status (C6 §11.4)"""

from __future__ import annotations

import pytest

from app.db.session import async_session
from app.models.bidder import Bidder
from app.models.project import Project
from app.models.user import User

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _disable_detect(monkeypatch):
    monkeypatch.setenv("INFRA_DISABLE_DETECT", "1")


async def _seed(owner_id: int, n: int = 2) -> int:
    async with async_session() as s:
        p = Project(name="p", status="ready", owner_id=owner_id)
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


async def test_status_before_start(
    seeded_reviewer: User, reviewer_token, auth_client
):
    """从未检测过 → version=None, agent_tasks=[], project_status=ready。"""
    pid = await _seed(seeded_reviewer.id)
    client = await auth_client(reviewer_token)
    resp = await client.get(f"/api/projects/{pid}/analysis/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] is None
    assert body["project_status"] == "ready"
    assert body["agent_tasks"] == []


async def test_status_after_start(
    seeded_reviewer: User, reviewer_token, auth_client
):
    pid = await _seed(seeded_reviewer.id)
    client = await auth_client(reviewer_token)
    await client.post(f"/api/projects/{pid}/analysis/start")

    resp = await client.get(f"/api/projects/{pid}/analysis/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 1
    assert body["project_status"] == "analyzing"
    assert len(body["agent_tasks"]) == 13  # fix-bug-triple: 7 pair + 6 global
    assert all(t["status"] == "pending" for t in body["agent_tasks"])


async def test_status_non_owner_404(
    seeded_reviewer: User, reviewer_token, auth_client
):
    from app.services.auth.password import hash_password

    async with async_session() as s:
        u = User(
            username="other_user",
            password_hash=hash_password("pw1234567"),
            role="reviewer",
            is_active=True,
            must_change_password=False,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        pid = await _seed(u.id)

    client = await auth_client(reviewer_token)
    resp = await client.get(f"/api/projects/{pid}/analysis/status")
    assert resp.status_code == 404
