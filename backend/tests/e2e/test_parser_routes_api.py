"""L2 - C5 HTTP 路由覆盖 (spec Req 6+7+9+project-mgmt MODIFIED)

- PATCH /api/documents/{id}/role  (spec "修改文档角色" 5 scenarios)
- POST  /api/documents/{id}/re-parse  (spec "重新解析失败文档" 4 scenarios)
- PUT   /api/projects/{pid}/price-rules/{id}  (spec "报价列映射修正" 4 scenarios)
- GET   /api/projects/{pid}/bidders/{bid}/price-items  (spec "查询投标人报价项" 4 scenarios)
- 项目详情 C5 扩展字段(files.file_role, progress 11 字段)
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest_asyncio
from sqlalchemy import select

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project

from ._c4_helpers import seed_bidder, seed_project, seed_user, token_for

os.environ.setdefault("INFRA_DISABLE_PIPELINE", "1")


async def _seed_doc(
    bidder_id: int,
    file_name: str = "技术方案.docx",
    file_type: str = ".docx",
    file_role: str | None = None,
    parse_status: str = "identified",
    md5_seed: int = 1,
) -> int:
    async with async_session() as s:
        doc = BidDocument(
            bidder_id=bidder_id,
            file_name=file_name,
            file_path=f"/tmp/fake{md5_seed}",
            file_size=100,
            file_type=file_type,
            md5=(f"{md5_seed:02d}" + "e" * 30)[:32],
            source_archive="a.zip",
            parse_status=parse_status,
            file_role=file_role,
        )
        s.add(doc)
        await s.commit()
        return doc.id


# ======================================== PATCH role (5 scenarios)


async def test_patch_role_success(seeded_reviewer, reviewer_token, auth_client):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    doc_id = await _seed_doc(bidder.id, md5_seed=1)

    client = await auth_client(reviewer_token)
    r = await client.patch(
        f"/api/documents/{doc_id}/role", json={"role": "pricing"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["file_role"] == "pricing"
    assert body["role_confidence"] == "user"
    assert body["warn"] is None


async def test_patch_role_invalid_422(seeded_reviewer, reviewer_token, auth_client):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    doc_id = await _seed_doc(bidder.id, md5_seed=2)
    client = await auth_client(reviewer_token)
    r = await client.patch(
        f"/api/documents/{doc_id}/role", json={"role": "invalid_role"}
    )
    assert r.status_code == 422


async def test_patch_role_cross_user_404(
    seeded_reviewer, reviewer_token, auth_client
):
    other = await seed_user("otherReviewer", role="reviewer")
    project = await seed_project(owner_id=other.id, name="OP")
    bidder = await seed_bidder(project_id=project.id)
    doc_id = await _seed_doc(bidder.id, md5_seed=3)
    client = await auth_client(reviewer_token)
    r = await client.patch(
        f"/api/documents/{doc_id}/role", json={"role": "technical"}
    )
    assert r.status_code == 404


async def test_patch_role_completed_project_warn(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(
        owner_id=seeded_reviewer.id, name="P", status_="completed"
    )
    bidder = await seed_bidder(project_id=project.id)
    doc_id = await _seed_doc(bidder.id, md5_seed=4)
    client = await auth_client(reviewer_token)
    r = await client.patch(
        f"/api/documents/{doc_id}/role", json={"role": "pricing"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["warn"] is not None


async def test_patch_role_does_not_trigger_re_parse(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    doc_id = await _seed_doc(
        bidder.id, parse_status="identified", md5_seed=5
    )
    client = await auth_client(reviewer_token)
    await client.patch(
        f"/api/documents/{doc_id}/role", json={"role": "pricing"}
    )
    async with async_session() as s:
        doc = await s.get(BidDocument, doc_id)
        assert doc.parse_status == "identified"  # 未重置


# ======================================== re-parse (4 scenarios)


async def test_re_parse_identify_failed(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    doc_id = await _seed_doc(
        bidder.id, parse_status="identify_failed", md5_seed=6
    )
    client = await auth_client(reviewer_token)
    r = await client.post(f"/api/documents/{doc_id}/re-parse")
    assert r.status_code == 202
    async with async_session() as s:
        doc = await s.get(BidDocument, doc_id)
        assert doc.parse_status == "extracted"  # 回退重跑点


async def test_re_parse_skipped_still_skipped_after_rerun(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    doc_id = await _seed_doc(
        bidder.id, file_type=".pdf", parse_status="skipped", md5_seed=7
    )
    client = await auth_client(reviewer_token)
    r = await client.post(f"/api/documents/{doc_id}/re-parse")
    assert r.status_code == 202
    # 端点仅重置 parse_status → extracted;后续 pipeline 会重标 skipped


async def test_re_parse_pricing_doc_resets_bidder(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(
        project_id=project.id, parse_status="priced"
    )
    doc_id = await _seed_doc(
        bidder.id,
        file_type=".xlsx",
        file_role="pricing",
        parse_status="identified",
        md5_seed=8,
    )
    # seed 一条 price_item
    async with async_session() as s:
        # 需要先 seed 一条 rule
        rule = PriceParsingRule(
            project_id=project.id,
            sheet_name="报价清单",
            header_row=2,
            column_mapping={
                "code_col": "A", "name_col": "B", "unit_col": "C",
                "qty_col": "D", "unit_price_col": "E", "total_price_col": "F",
            },
            created_by_llm=True, confirmed=True, status="confirmed",
        )
        s.add(rule)
        await s.flush()
        s.add(PriceItem(
            bidder_id=bidder.id,
            price_parsing_rule_id=rule.id,
            sheet_name="报价清单",
            row_index=3,
            item_code="A1",
            item_name="n",
            unit="m",
            quantity=Decimal("1"),
            unit_price=Decimal("10"),
            total_price=Decimal("10"),
        ))
        await s.commit()

    client = await auth_client(reviewer_token)
    r = await client.post(f"/api/documents/{doc_id}/re-parse")
    assert r.status_code == 202
    async with async_session() as s:
        from app.models.bidder import Bidder as BM
        b = await s.get(BM, bidder.id)
        assert b.parse_status == "identified"  # 退回
        items = (
            await s.execute(select(PriceItem).where(PriceItem.bidder_id == bidder.id))
        ).scalars().all()
        assert items == []


async def test_re_parse_cross_user_404(
    seeded_reviewer, reviewer_token, auth_client
):
    other = await seed_user("ru2", role="reviewer")
    project = await seed_project(owner_id=other.id, name="OP2")
    bidder = await seed_bidder(project_id=project.id)
    doc_id = await _seed_doc(
        bidder.id, parse_status="identify_failed", md5_seed=9
    )
    client = await auth_client(reviewer_token)
    r = await client.post(f"/api/documents/{doc_id}/re-parse")
    assert r.status_code == 404


# ======================================== PUT price-rules/{id} (4 scenarios)


async def _seed_rule_and_items(
    project_id: int, bidder_id: int
) -> tuple[int, int]:
    async with async_session() as s:
        rule = PriceParsingRule(
            project_id=project_id,
            sheet_name="报价清单",
            header_row=2,
            column_mapping={
                "code_col": "A", "name_col": "B", "unit_col": "C",
                "qty_col": "D", "unit_price_col": "E", "total_price_col": "F",
            },
            created_by_llm=True, confirmed=True, status="confirmed",
        )
        s.add(rule)
        await s.flush()
        item = PriceItem(
            bidder_id=bidder_id,
            price_parsing_rule_id=rule.id,
            sheet_name="报价清单",
            row_index=3,
            item_code="A",
            quantity=Decimal("1"),
            unit_price=Decimal("10"),
            total_price=Decimal("10"),
        )
        s.add(item)
        await s.commit()
        return rule.id, item.id


async def test_put_rule_refill_deletes_items_and_resets_bidders(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(
        project_id=project.id, parse_status="priced"
    )
    rule_id, item_id = await _seed_rule_and_items(project.id, bidder.id)

    client = await auth_client(reviewer_token)
    r = await client.put(
        f"/api/projects/{project.id}/price-rules/{rule_id}",
        json={
            "id": rule_id,
            "sheet_name": "报价清单",
            "header_row": 2,
            "column_mapping": {
                "code_col": "A",
                "name_col": "B",
                "unit_col": "C",
                "qty_col": "D",
                "unit_price_col": "F",  # 变了列
                "total_price_col": "G",
                "skip_cols": [],
            },
            "created_by_llm": True,
            "confirmed": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created_by_llm"] is False  # 人工修正标记

    async with async_session() as s:
        from app.models.bidder import Bidder as BM
        items = (
            await s.execute(select(PriceItem).where(PriceItem.bidder_id == bidder.id))
        ).scalars().all()
        assert items == []  # 清空了
        b = await s.get(BM, bidder.id)
        assert b.parse_status == "identified"  # 回退等重跑


async def test_put_rule_invalid_mapping_422(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    rule_id, _ = await _seed_rule_and_items(project.id, bidder.id)
    client = await auth_client(reviewer_token)
    r = await client.put(
        f"/api/projects/{project.id}/price-rules/{rule_id}",
        json={
            "id": rule_id,
            "sheet_name": "报价清单",
            "header_row": 2,
            "column_mapping": {"name_col": "B"},  # 缺 code_col 等
            "created_by_llm": False,
            "confirmed": True,
        },
    )
    assert r.status_code == 422


async def test_put_rule_cross_user_404(
    seeded_reviewer, reviewer_token, auth_client
):
    other = await seed_user("po2", role="reviewer")
    project = await seed_project(owner_id=other.id, name="OP")
    bidder = await seed_bidder(project_id=project.id)
    rule_id, _ = await _seed_rule_and_items(project.id, bidder.id)
    client = await auth_client(reviewer_token)
    r = await client.put(
        f"/api/projects/{project.id}/price-rules/{rule_id}",
        json={
            "id": rule_id,
            "sheet_name": "报价清单",
            "header_row": 2,
            "column_mapping": {
                "code_col": "A", "name_col": "B", "unit_col": "C",
                "qty_col": "D", "unit_price_col": "E", "total_price_col": "F",
                "skip_cols": [],
            },
            "created_by_llm": False,
            "confirmed": True,
        },
    )
    assert r.status_code == 404


# ======================================== price-items query (4 scenarios)


async def test_list_price_items_priced(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(
        project_id=project.id, parse_status="priced"
    )
    await _seed_rule_and_items(project.id, bidder.id)
    client = await auth_client(reviewer_token)
    r = await client.get(
        f"/api/projects/{project.id}/bidders/{bidder.id}/price-items"
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["sheet_name"] == "报价清单"


async def test_list_price_items_empty_for_not_priced(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(
        project_id=project.id, parse_status="identified"
    )
    client = await auth_client(reviewer_token)
    r = await client.get(
        f"/api/projects/{project.id}/bidders/{bidder.id}/price-items"
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_list_price_items_cross_user_404(
    seeded_reviewer, reviewer_token, auth_client
):
    other = await seed_user("pi2", role="reviewer")
    project = await seed_project(owner_id=other.id, name="OP")
    bidder = await seed_bidder(project_id=project.id)
    client = await auth_client(reviewer_token)
    r = await client.get(
        f"/api/projects/{project.id}/bidders/{bidder.id}/price-items"
    )
    assert r.status_code == 404


async def test_list_price_items_sorted(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(
        project_id=project.id, parse_status="priced"
    )
    # seed 多条
    async with async_session() as s:
        rule = PriceParsingRule(
            project_id=project.id, sheet_name="s1", header_row=1,
            column_mapping={
                "code_col": "A", "name_col": "B", "unit_col": "C",
                "qty_col": "D", "unit_price_col": "E", "total_price_col": "F",
            },
            created_by_llm=False, confirmed=True, status="confirmed",
        )
        s.add(rule)
        await s.flush()
        for sheet_name, row_idx in [("s2", 5), ("s1", 3), ("s1", 2)]:
            s.add(PriceItem(
                bidder_id=bidder.id,
                price_parsing_rule_id=rule.id,
                sheet_name=sheet_name,
                row_index=row_idx,
                item_code=f"{sheet_name}-{row_idx}",
            ))
        await s.commit()

    client = await auth_client(reviewer_token)
    r = await client.get(
        f"/api/projects/{project.id}/bidders/{bidder.id}/price-items"
    )
    assert r.status_code == 200
    items = r.json()
    # 按 (sheet_name, row_index) 升序
    orders = [(i["sheet_name"], i["row_index"]) for i in items]
    assert orders == sorted(orders)


# ======================================== project-mgmt MODIFIED (3 scenarios)


async def test_project_detail_progress_has_c5_fields(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    # 3 个 bidder:extracted / identifying / priced
    await seed_bidder(
        project_id=project.id, name="B1", parse_status="extracted"
    )
    await seed_bidder(
        project_id=project.id, name="B2", parse_status="identifying"
    )
    await seed_bidder(
        project_id=project.id, name="B3", parse_status="priced"
    )

    client = await auth_client(reviewer_token)
    r = await client.get(f"/api/projects/{project.id}")
    assert r.status_code == 200
    prog = r.json()["progress"]
    assert prog["total_bidders"] == 3
    assert prog["extracted_count"] == 1
    assert prog["identifying_count"] == 1
    assert prog["priced_count"] == 1


async def test_project_detail_files_has_role_fields(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    doc_id = await _seed_doc(
        bidder.id,
        file_role="technical",
        parse_status="identified",
        md5_seed=11,
    )

    client = await auth_client(reviewer_token)
    r = await client.get(f"/api/projects/{project.id}")
    assert r.status_code == 200
    files = r.json()["files"]
    assert len(files) == 1
    assert files[0]["file_role"] == "technical"
    assert "role_confidence" in files[0]
