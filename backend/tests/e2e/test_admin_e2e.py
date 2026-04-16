"""L2 admin E2E 测试 (C17 admin-users)

3 cases:
- 10.1: admin 创建用户→新用户登录→admin 禁用→登录失败
- 10.2: admin 修改规则→GET 返回新值→恢复默认→GET 返回默认值
- 10.3: reviewer 调用 admin API → 全部 403
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.asyncio]


async def test_user_lifecycle(seeded_admin, admin_token, auth_client):
    """admin 创建用户→新用户登录→admin 禁用→登录失败。"""
    admin = await auth_client(admin_token)

    # 1. admin 创建用户
    r = await admin.post(
        "/api/admin/users",
        json={"username": "e2e_user", "password": "E2eTest1234", "role": "reviewer"},
    )
    assert r.status_code == 201
    new_user_id = r.json()["id"]

    # 2. 新用户登录成功
    anon = await auth_client(None)
    r = await anon.post(
        "/api/auth/login",
        json={"username": "e2e_user", "password": "E2eTest1234"},
    )
    assert r.status_code == 200
    new_token = r.json()["access_token"]

    # 3. 新用户可以调 API（改密页面除外，因为 must_change_password=true
    #    但 /api/auth/me 在 deps 里不检查 must_change_password，只在前端跳转）
    new_client = await auth_client(new_token)
    r = await new_client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["username"] == "e2e_user"

    # 4. admin 禁用该用户
    r = await admin.patch(
        f"/api/admin/users/{new_user_id}", json={"is_active": False}
    )
    assert r.status_code == 200

    # 5. 被禁用用户的后续请求返回 403（get_current_user 检查 is_active=false）
    #    注意：由于 deps.py 中 require_role 检查 is_active，但 get_current_user 本身
    #    不检查 is_active（只有 require_role 检查），所以需要通过受保护的路由测试
    #    这里测试登录：禁用后登录会被 auth 路由拦截返回 403
    r = await anon.post(
        "/api/auth/login",
        json={"username": "e2e_user", "password": "E2eTest1234"},
    )
    assert r.status_code == 403


async def test_rules_lifecycle(seeded_admin, admin_token, auth_client):
    """admin 修改规则→GET 返回新值→恢复默认→GET 返回默认值。"""
    client = await auth_client(admin_token)

    # 1. GET 默认配置
    r = await client.get("/api/admin/rules")
    assert r.status_code == 200
    original = r.json()["config"]
    assert original["risk_levels"]["high"] == 70

    # 2. PUT 修改配置
    modified = dict(original)
    modified["risk_levels"] = {"high": 80, "medium": 50}
    r = await client.put("/api/admin/rules", json=modified)
    assert r.status_code == 200

    # 3. GET 验证新值
    r = await client.get("/api/admin/rules")
    assert r.json()["config"]["risk_levels"]["high"] == 80
    assert r.json()["config"]["risk_levels"]["medium"] == 50

    # 4. 恢复默认
    r = await client.put(
        "/api/admin/rules", json={"restore_defaults": True}
    )
    assert r.status_code == 200

    # 5. GET 验证默认值
    r = await client.get("/api/admin/rules")
    assert r.json()["config"]["risk_levels"]["high"] == 70
    assert r.json()["config"]["risk_levels"]["medium"] == 40


async def test_reviewer_all_403(
    seeded_admin, seeded_reviewer, reviewer_token, auth_client
):
    """reviewer 调用所有 admin API → 403。"""
    client = await auth_client(reviewer_token)

    r = await client.get("/api/admin/users")
    assert r.status_code == 403

    r = await client.post(
        "/api/admin/users",
        json={"username": "x", "password": "Test1234", "role": "reviewer"},
    )
    assert r.status_code == 403

    r = await client.patch("/api/admin/users/1", json={"is_active": False})
    assert r.status_code == 403

    r = await client.get("/api/admin/rules")
    assert r.status_code == 403

    r = await client.put(
        "/api/admin/rules", json={"restore_defaults": True}
    )
    assert r.status_code == 403
