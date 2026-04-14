"""L2: 报价配置 + 列映射规则骨架 (C4 file-upload §11.8)。

覆盖 spec.md "项目报价元配置" (5 scenarios) + "报价列映射规则骨架" (5 scenarios)。
"""

from __future__ import annotations

from ._c4_helpers import seed_project, seed_user


_VALID_MAPPING = {
    "code_col": "A",
    "name_col": "B",
    "unit_col": "C",
    "qty_col": "D",
    "unit_price_col": "E",
    "total_price_col": "F",
}


# ============================================================ price-config

async def test_price_config_first_get_returns_null(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    client = await auth_client(reviewer_token)

    r = await client.get(f"/api/projects/{project.id}/price-config")
    assert r.status_code == 200
    assert r.json() is None


async def test_price_config_put_creates(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    client = await auth_client(reviewer_token)

    r = await client.put(
        f"/api/projects/{project.id}/price-config",
        json={"currency": "CNY", "tax_inclusive": True, "unit_scale": "yuan"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["currency"] == "CNY"
    assert body["tax_inclusive"] is True
    assert body["unit_scale"] == "yuan"

    # 再读
    r2 = await client.get(f"/api/projects/{project.id}/price-config")
    assert r2.json()["currency"] == "CNY"


async def test_price_config_put_overwrites(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    client = await auth_client(reviewer_token)

    await client.put(
        f"/api/projects/{project.id}/price-config",
        json={"currency": "CNY", "tax_inclusive": True, "unit_scale": "yuan"},
    )
    r = await client.put(
        f"/api/projects/{project.id}/price-config",
        json={"currency": "USD", "tax_inclusive": False, "unit_scale": "wan_yuan"},
    )
    assert r.status_code == 200
    assert r.json()["currency"] == "USD"
    assert r.json()["tax_inclusive"] is False


async def test_price_config_illegal_currency_422(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    client = await auth_client(reviewer_token)

    r = await client.put(
        f"/api/projects/{project.id}/price-config",
        json={"currency": "JPY", "tax_inclusive": True, "unit_scale": "yuan"},
    )
    assert r.status_code == 422


async def test_price_config_cross_user_404(
    seeded_reviewer, reviewer_token, auth_client
):
    other = await seed_user("o-x", "reviewer")
    other_proj = await seed_project(owner_id=other.id, name="op")
    client = await auth_client(reviewer_token)

    r = await client.get(f"/api/projects/{other_proj.id}/price-config")
    assert r.status_code == 404
    r = await client.put(
        f"/api/projects/{other_proj.id}/price-config",
        json={"currency": "CNY", "tax_inclusive": True, "unit_scale": "yuan"},
    )
    assert r.status_code == 404


# ============================================================ price-rules

async def test_price_rules_empty_list(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    client = await auth_client(reviewer_token)

    r = await client.get(f"/api/projects/{project.id}/price-rules")
    assert r.status_code == 200
    assert r.json() == []


async def test_price_rules_put_inserts(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    client = await auth_client(reviewer_token)

    r = await client.put(
        f"/api/projects/{project.id}/price-rules",
        json={
            "sheet_name": "报价清单",
            "header_row": 2,
            "column_mapping": _VALID_MAPPING,
            "created_by_llm": True,
        },
    )
    assert r.status_code == 200
    rid = r.json()["id"]

    r2 = await client.get(f"/api/projects/{project.id}/price-rules")
    assert len(r2.json()) == 1
    assert r2.json()[0]["id"] == rid
    assert r2.json()[0]["confirmed"] is False


async def test_price_rules_put_updates_confirmed(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    client = await auth_client(reviewer_token)

    r = await client.put(
        f"/api/projects/{project.id}/price-rules",
        json={
            "sheet_name": "x",
            "header_row": 1,
            "column_mapping": _VALID_MAPPING,
            "created_by_llm": True,
            "confirmed": False,
        },
    )
    rid = r.json()["id"]
    r2 = await client.put(
        f"/api/projects/{project.id}/price-rules",
        json={
            "id": rid,
            "sheet_name": "x",
            "header_row": 1,
            "column_mapping": _VALID_MAPPING,
            "created_by_llm": True,
            "confirmed": True,
        },
    )
    assert r2.status_code == 200
    assert r2.json()["confirmed"] is True


async def test_price_rules_missing_required_key_422(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    client = await auth_client(reviewer_token)

    bad = {k: v for k, v in _VALID_MAPPING.items() if k != "code_col"}
    r = await client.put(
        f"/api/projects/{project.id}/price-rules",
        json={"sheet_name": "x", "header_row": 1, "column_mapping": bad},
    )
    assert r.status_code == 422


async def test_price_rules_cross_user_404(
    seeded_reviewer, reviewer_token, auth_client
):
    other = await seed_user("o-y", "reviewer")
    other_proj = await seed_project(owner_id=other.id, name="op")
    client = await auth_client(reviewer_token)

    r = await client.get(f"/api/projects/{other_proj.id}/price-rules")
    assert r.status_code == 404
    r = await client.put(
        f"/api/projects/{other_proj.id}/price-rules",
        json={
            "sheet_name": "x",
            "header_row": 1,
            "column_mapping": _VALID_MAPPING,
        },
    )
    assert r.status_code == 404
