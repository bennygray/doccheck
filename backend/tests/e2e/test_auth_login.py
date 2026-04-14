"""L2: 登录端到端 (C2).

覆盖:正确凭证 / 错密 / 不存在用户 / 已禁用用户。
"""

from __future__ import annotations

from sqlalchemy import select, update

from app.db.session import async_session
from app.models.user import User


async def test_login_success(seeded_admin, auth_client):
    client = await auth_client(None)
    r = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "admin"


async def test_login_wrong_password_returns_generic_401(seeded_admin, auth_client):
    client = await auth_client(None)
    r = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert r.status_code == 401
    detail = r.json()["detail"]
    # 通用文案,不泄露用户名 vs 密码哪个错
    assert "用户名或密码错误" in detail


async def test_login_unknown_user_generic_401_and_no_counter(seeded_admin, auth_client):
    client = await auth_client(None)
    # 多次尝试不存在用户
    for _ in range(10):
        r = await client.post(
            "/api/auth/login",
            json={"username": "no-such-user", "password": "whatever"},
        )
        assert r.status_code == 401
        assert "用户名或密码错误" in r.json()["detail"]

    # 真实 admin 的 login_fail_count 未被污染
    async with async_session() as s:
        row = (await s.execute(select(User.login_fail_count).where(User.username == "admin"))).scalar_one()
        assert row == 0


async def test_login_inactive_user_returns_403(seeded_admin, auth_client):
    async with async_session() as s:
        await s.execute(update(User).where(User.username == "admin").values(is_active=False))
        await s.commit()

    client = await auth_client(None)
    r = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert r.status_code == 403
