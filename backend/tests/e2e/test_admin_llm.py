"""L2 admin-llm-config E2E 测试

覆盖 Req-1~Req-5:
- GET:admin 能读,返脱敏
- PUT:写入 + 再 GET 返新值;空 api_key 保持旧值
- POST /test:mock 连通性
- 非 admin 403
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.asyncio]


async def test_llm_get_admin_ok(seeded_admin, admin_token, auth_client):
    """admin GET /api/admin/llm 返回脱敏配置。"""
    client = await auth_client(admin_token)
    r = await client.get("/api/admin/llm")
    assert r.status_code == 200
    data = r.json()
    assert "provider" in data
    assert "api_key_masked" in data
    assert "model" in data
    assert "timeout_s" in data
    assert "source" in data
    # source 应该是 db/env/default 之一
    assert data["source"] in {"db", "env", "default"}


async def test_llm_put_updates_config(seeded_admin, admin_token, auth_client):
    """PUT 写入后 GET 返新值,api_key 脱敏。"""
    client = await auth_client(admin_token)

    payload = {
        "provider": "openai",
        "api_key": "sk-test1234567890",
        "model": "gpt-4o-mini",
        "base_url": None,
        "timeout_s": 45,
    }
    r = await client.put("/api/admin/llm", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o-mini"
    assert data["timeout_s"] == 45
    # 脱敏(末 4 位可见)
    assert data["api_key_masked"] == "sk-****7890"
    assert data["source"] == "db"

    # 再 GET 验证持久化
    r2 = await client.get("/api/admin/llm")
    assert r2.json()["model"] == "gpt-4o-mini"


async def test_llm_put_empty_key_preserves_old(seeded_admin, admin_token, auth_client):
    """PUT 时 api_key 空字符串/缺失 → 保持旧 key 不变(Req-3 场景 2)。"""
    client = await auth_client(admin_token)

    # 先设一个 key
    await client.put(
        "/api/admin/llm",
        json={
            "provider": "dashscope",
            "api_key": "sk-original9999",
            "model": "qwen-plus",
            "base_url": None,
            "timeout_s": 30,
        },
    )

    # 再 PUT 不带 api_key → 仅改 model
    r = await client.put(
        "/api/admin/llm",
        json={
            "provider": "dashscope",
            "model": "qwen-turbo",
            "base_url": None,
            "timeout_s": 30,
        },
    )
    assert r.status_code == 200
    # api_key 末 4 位应该仍然是 "9999"
    assert r.json()["api_key_masked"] == "sk-****9999"
    assert r.json()["model"] == "qwen-turbo"


async def test_llm_put_invalid_provider_422(seeded_admin, admin_token, auth_client):
    client = await auth_client(admin_token)
    r = await client.put(
        "/api/admin/llm",
        json={
            "provider": "unknown",
            "model": "foo",
            "base_url": None,
            "timeout_s": 30,
        },
    )
    assert r.status_code == 422


async def test_llm_put_invalid_base_url_422(seeded_admin, admin_token, auth_client):
    client = await auth_client(admin_token)
    r = await client.put(
        "/api/admin/llm",
        json={
            "provider": "custom",
            "model": "foo",
            "base_url": "not-a-url",
            "timeout_s": 30,
        },
    )
    assert r.status_code == 422


async def test_llm_reviewer_forbidden(
    seeded_admin, seeded_reviewer, reviewer_token, auth_client
):
    """非 admin 调 GET/PUT/test 全部 403。"""
    client = await auth_client(reviewer_token)
    r = await client.get("/api/admin/llm")
    assert r.status_code == 403

    r = await client.put(
        "/api/admin/llm",
        json={
            "provider": "dashscope",
            "model": "qwen-plus",
            "base_url": None,
            "timeout_s": 30,
        },
    )
    assert r.status_code == 403

    r = await client.post("/api/admin/llm/test", json={})
    assert r.status_code == 403


async def test_llm_test_connection_mocked_ok(
    seeded_admin, admin_token, auth_client
):
    """POST /llm/test 成功路径(mock tester)。"""
    client = await auth_client(admin_token)
    with patch(
        "app.api.routes.admin.test_connection",
        return_value=(True, 120, None),
    ):
        r = await client.post(
            "/api/admin/llm/test",
            json={
                "provider": "openai",
                "api_key": "sk-fake",
                "model": "gpt-4",
                "base_url": None,
                "timeout_s": 5,
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["latency_ms"] == 120
    assert data["error"] is None


async def test_llm_test_connection_mocked_fail(
    seeded_admin, admin_token, auth_client
):
    """POST /llm/test 失败路径(mock tester 返 error)。"""
    client = await auth_client(admin_token)
    with patch(
        "app.api.routes.admin.test_connection",
        return_value=(False, 3020, "timeout after 3s"),
    ):
        r = await client.post("/api/admin/llm/test", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["error"] == "timeout after 3s"
