"""L2: 账户锁定 E2E (C2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.core.config import settings
from app.db.session import async_session
from app.models.user import User


async def test_five_failures_then_429(seeded_admin, auth_client):
    client = await auth_client(None)
    # 连续阈值次错密
    for i in range(settings.auth_lockout_threshold):
        r = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        assert r.status_code == 401, f"attempt {i} expected 401"

    # 第 threshold+1 次 → 即使密码正确也返 429
    r = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert r.status_code == 429
    body = r.json()
    detail = body["detail"]
    assert "retry_after_seconds" in detail
    assert detail["retry_after_seconds"] > 0
    # Retry-After 头也应存在
    assert "retry-after" in {k.lower() for k in r.headers.keys()}


async def test_lockout_expires_then_login_allowed(seeded_admin, auth_client):
    # 人为设置 locked_until 到过去 → 下一次登录应放行
    async with async_session() as s:
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        await s.execute(
            update(User).where(User.username == "admin").values(locked_until=past)
        )
        await s.commit()

    client = await auth_client(None)
    r = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert r.status_code == 200

    # 成功后 locked_until 清零
    async with async_session() as s:
        lock = (
            await s.execute(select(User.locked_until).where(User.username == "admin"))
        ).scalar_one()
        assert lock is None
