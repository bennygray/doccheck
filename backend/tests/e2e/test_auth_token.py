"""L2: JWT 与角色守卫 E2E (C2).

测试通过动态挂一个 admin-only 路由验证 require_role 行为。
"""

from __future__ import annotations

from fastapi import Depends, FastAPI

from app.api.deps import get_current_user, require_role
from app.api.routes import auth as auth_routes
from app.services.auth.jwt import create_access_token


def _build_test_app() -> FastAPI:
    """独立 FastAPI 实例:只挂 auth + 两个最小受保护端点,避免污染生产 app。"""
    test_app = FastAPI()
    test_app.include_router(auth_routes.router, prefix="/api/auth")

    @test_app.get("/api/test/authed")
    async def _authed(user=Depends(get_current_user)):
        return {"username": user.username, "role": user.role}

    @test_app.get("/api/test/admin-only")
    async def _admin_only(user=Depends(require_role("admin"))):
        return {"username": user.username}

    return test_app


async def test_no_token_returns_401(seeded_admin):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=_build_test_app()), base_url="http://test"
    ) as c:
        r = await c.get("/api/test/authed")
        assert r.status_code == 401


async def test_expired_token_returns_401(seeded_admin):
    from httpx import ASGITransport, AsyncClient

    expired = create_access_token(
        user_id=seeded_admin.id,
        role=seeded_admin.role,
        pwd_v=int(seeded_admin.password_changed_at.timestamp()),
        username=seeded_admin.username,
        expires_minutes=-1,
    )
    async with AsyncClient(
        transport=ASGITransport(app=_build_test_app()), base_url="http://test"
    ) as c:
        r = await c.get(
            "/api/test/authed", headers={"Authorization": f"Bearer {expired}"}
        )
        assert r.status_code == 401


async def test_reviewer_token_forbidden_on_admin_route(
    seeded_reviewer, reviewer_token
):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=_build_test_app()), base_url="http://test"
    ) as c:
        r = await c.get(
            "/api/test/admin-only",
            headers={"Authorization": f"Bearer {reviewer_token}"},
        )
        assert r.status_code == 403


async def test_admin_token_allowed_on_admin_route(seeded_admin, admin_token):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=_build_test_app()), base_url="http://test"
    ) as c:
        r = await c.get(
            "/api/test/admin-only",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        assert r.json()["username"] == seeded_admin.username


async def test_garbage_token_returns_401(seeded_admin):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=_build_test_app()), base_url="http://test"
    ) as c:
        r = await c.get(
            "/api/test/authed", headers={"Authorization": "Bearer not.a.real.jwt"}
        )
        assert r.status_code == 401
