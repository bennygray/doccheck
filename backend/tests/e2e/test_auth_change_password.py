"""L2: 改密 E2E — 含"改密后旧 token 立即失效" (C2 核心)."""

from __future__ import annotations

from sqlalchemy import select

from app.db.session import async_session
from app.models.user import User


async def test_change_password_success_updates_flags(
    seeded_admin, admin_token, auth_client
):
    client = await auth_client(admin_token)
    r = await client.post(
        "/api/auth/change-password",
        json={"old_password": "admin123", "new_password": "NewStr0ng"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["must_change_password"] is False

    async with async_session() as s:
        u = (
            await s.execute(select(User).where(User.id == seeded_admin.id))
        ).scalar_one()
        assert u.must_change_password is False
        # 新哈希应能验证新密码
        from app.services.auth.password import verify_password

        assert verify_password("NewStr0ng", u.password_hash)
        assert not verify_password("admin123", u.password_hash)


async def test_old_token_invalidated_after_password_change(
    seeded_admin, admin_token, auth_client
):
    client = await auth_client(admin_token)

    # 改密前:旧 token 可用
    r = await client.get("/api/auth/me")
    assert r.status_code == 200

    # 改密
    r = await client.post(
        "/api/auth/change-password",
        json={"old_password": "admin123", "new_password": "NewStr0ng"},
    )
    assert r.status_code == 200

    # 改密后:同一旧 token 立即失效(pwd_v 不再匹配)
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_wrong_old_password_returns_400(seeded_admin, admin_token, auth_client):
    client = await auth_client(admin_token)
    r = await client.post(
        "/api/auth/change-password",
        json={"old_password": "WRONG", "new_password": "NewStr0ng"},
    )
    assert r.status_code == 400
    # DB 中密码未变
    async with async_session() as s:
        u = (
            await s.execute(select(User).where(User.id == seeded_admin.id))
        ).scalar_one()
        from app.services.auth.password import verify_password

        assert verify_password("admin123", u.password_hash)


async def test_weak_new_password_returns_422(seeded_admin, admin_token, auth_client):
    client = await auth_client(admin_token)
    r = await client.post(
        "/api/auth/change-password",
        json={"old_password": "admin123", "new_password": "short"},
    )
    assert r.status_code == 422

    r = await client.post(
        "/api/auth/change-password",
        json={"old_password": "admin123", "new_password": "nodigitinhere"},
    )
    assert r.status_code == 422

    r = await client.post(
        "/api/auth/change-password",
        json={"old_password": "admin123", "new_password": "12345678"},
    )
    assert r.status_code == 422


async def test_me_endpoint_returns_current_user(seeded_admin, admin_token, auth_client):
    client = await auth_client(admin_token)
    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == seeded_admin.username
    assert body["role"] == "admin"
    assert body["is_active"] is True


async def test_logout_returns_204(seeded_admin, admin_token, auth_client):
    client = await auth_client(admin_token)
    r = await client.post("/api/auth/logout")
    assert r.status_code == 204
