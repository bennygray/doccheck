"""L2: GET /api/projects/{pid}/analysis/events SSE (C6 §11.5)

SSE 流式断开在 httpx ASGITransport 下不可靠(C5 已验证,见 design.md D5 解释)。
L2 仅覆盖权限 404 路径;snapshot / heartbeat / agent_status 事件由:
- unit test_progress_broker / test_detect_engine(publish 调用)
- L3 Playwright 用真实 backend + EventSource
覆盖。
"""

from __future__ import annotations

import pytest

from app.db.session import async_session
from app.models.bidder import Bidder
from app.models.project import Project
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _seed(owner_id: int) -> int:
    async with async_session() as s:
        p = Project(name="p", status="ready", owner_id=owner_id)
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
        return p.id


async def test_sse_non_owner_404(
    seeded_reviewer: User, reviewer_token, auth_client
):
    from app.services.auth.password import hash_password

    async with async_session() as s:
        u = User(
            username="other_sse",
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
    resp = await client.get(f"/api/projects/{pid}/analysis/events")
    assert resp.status_code == 404


async def test_sse_unauth_401(auth_client):
    client = await auth_client(None)
    resp = await client.get("/api/projects/1/analysis/events")
    assert resp.status_code == 401


async def test_sse_route_registered(
    seeded_reviewer: User, reviewer_token, auth_client
):
    """端点挂在正确 path 下:访问不存在 project → 404(非 405 method not allowed)。"""
    client = await auth_client(reviewer_token)
    resp = await client.get("/api/projects/99999/analysis/events")
    assert resp.status_code == 404
