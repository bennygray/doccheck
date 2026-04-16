"""L1 admin users API 测试 (C17 admin-users)

7 cases: 列表/创建/禁用/self-禁用400/重复用户名409/弱密码422/reviewer 403
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.asyncio]


@pytest.fixture
async def admin_client(seeded_admin, admin_token, auth_client):
    return await auth_client(admin_token)


@pytest.fixture
async def reviewer_client(seeded_reviewer, reviewer_token, auth_client):
    return await auth_client(reviewer_token)


async def test_list_users(admin_client, seeded_admin):
    r = await admin_client.get("/api/admin/users")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert any(u["username"] == "admin" for u in data)
    # 不暴露 password_hash
    assert all("password_hash" not in u for u in data)


async def test_create_user_success(admin_client):
    r = await admin_client.post(
        "/api/admin/users",
        json={"username": "newuser1", "password": "Test1234", "role": "reviewer"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["username"] == "newuser1"
    assert data["role"] == "reviewer"
    assert data["is_active"] is True
    assert data["must_change_password"] is True


async def test_disable_user(admin_client, seeded_reviewer):
    # 先获取 reviewer id
    r = await admin_client.get("/api/admin/users")
    users = r.json()
    reviewer = next(u for u in users if u["username"] == "reviewer1")

    r = await admin_client.patch(
        f"/api/admin/users/{reviewer['id']}", json={"is_active": False}
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False


async def test_self_disable_400(admin_client, seeded_admin):
    r = await admin_client.get("/api/admin/users")
    admin_user = next(u for u in r.json() if u["username"] == "admin")

    r = await admin_client.patch(
        f"/api/admin/users/{admin_user['id']}", json={"is_active": False}
    )
    assert r.status_code == 400


async def test_duplicate_username_409(admin_client, seeded_admin):
    r = await admin_client.post(
        "/api/admin/users",
        json={"username": "admin", "password": "Test1234", "role": "reviewer"},
    )
    assert r.status_code == 409


async def test_weak_password_422(admin_client):
    r = await admin_client.post(
        "/api/admin/users",
        json={"username": "weakpwd", "password": "12345678", "role": "reviewer"},
    )
    assert r.status_code == 422


async def test_reviewer_403(reviewer_client):
    r = await reviewer_client.get("/api/admin/users")
    assert r.status_code == 403
