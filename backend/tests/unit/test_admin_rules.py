"""L1 admin rules API 测试 (C17 admin-users)

6 cases: GET 默认/PUT 合法/PUT 非法权重422/PUT risk_levels 不连续422/restore_defaults/reviewer 403
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


async def test_get_rules_default(admin_client):
    r = await admin_client.get("/api/admin/rules")
    assert r.status_code == 200
    data = r.json()
    assert "config" in data
    config = data["config"]
    assert "dimensions" in config
    assert "risk_levels" in config
    assert config["risk_levels"]["high"] == 70
    assert config["risk_levels"]["medium"] == 40


async def test_put_rules_valid(admin_client):
    # 先 GET 获取当前配置
    r = await admin_client.get("/api/admin/rules")
    config = r.json()["config"]

    # 修改一个权重
    config["dimensions"]["text_similarity"]["weight"] = 25

    r = await admin_client.put("/api/admin/rules", json=config)
    assert r.status_code == 200
    assert r.json()["config"]["dimensions"]["text_similarity"]["weight"] == 25

    # GET 验证持久化
    r = await admin_client.get("/api/admin/rules")
    assert r.json()["config"]["dimensions"]["text_similarity"]["weight"] == 25


async def test_put_negative_weight_422(admin_client):
    r = await admin_client.get("/api/admin/rules")
    config = r.json()["config"]
    config["dimensions"]["text_similarity"]["weight"] = -5

    r = await admin_client.put("/api/admin/rules", json=config)
    assert r.status_code == 422


async def test_put_risk_levels_invalid_422(admin_client):
    r = await admin_client.get("/api/admin/rules")
    config = r.json()["config"]
    # high < medium → 不连续
    config["risk_levels"] = {"high": 30, "medium": 50}

    r = await admin_client.put("/api/admin/rules", json=config)
    assert r.status_code == 422


async def test_restore_defaults(admin_client):
    # 先修改
    r = await admin_client.get("/api/admin/rules")
    config = r.json()["config"]
    config["dimensions"]["text_similarity"]["weight"] = 99

    await admin_client.put("/api/admin/rules", json=config)

    # 恢复默认
    r = await admin_client.put(
        "/api/admin/rules", json={"restore_defaults": True}
    )
    assert r.status_code == 200
    assert r.json()["config"]["dimensions"]["text_similarity"]["weight"] == 15


async def test_reviewer_403(reviewer_client):
    r = await reviewer_client.get("/api/admin/rules")
    assert r.status_code == 403
