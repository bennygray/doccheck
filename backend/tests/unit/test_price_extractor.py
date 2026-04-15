"""L1 - price_impl/extractor (C11)"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.session import async_session
from app.models.bidder import Bidder
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project
from app.models.user import User
from app.services.detect.agents.price_impl.config import (
    PriceConfig,
    AmountPatternConfig,
    ItemListConfig,
    ScorerConfig,
    SeriesConfig,
    TailConfig,
    load_price_config,
)
from app.services.detect.agents.price_impl.extractor import (
    extract_bidder_prices,
    flatten_rows,
)


@pytest_asyncio.fixture
async def clean_prices():
    async with async_session() as s:
        await s.execute(delete(PriceItem))
        await s.execute(delete(Bidder))
        await s.execute(delete(PriceParsingRule))
        await s.execute(delete(Project))
        await s.execute(delete(User))
        await s.commit()
    yield
    async with async_session() as s:
        await s.execute(delete(PriceItem))
        await s.execute(delete(Bidder))
        await s.execute(delete(PriceParsingRule))
        await s.execute(delete(Project))
        await s.execute(delete(User))
        await s.commit()


async def _seed_bidder_with_items(items: list[dict]) -> int:
    """Seed 一个 bidder + 一条 price_parsing_rule + 多个 PriceItem。"""
    async with async_session() as s:
        u = User(username=f"u_{id(s)}", password_hash="x", role="reviewer")
        s.add(u)
        await s.flush()
        p = Project(name="P_ex", owner_id=u.id)
        s.add(p)
        await s.flush()
        rule = PriceParsingRule(
            project_id=p.id,
            sheet_name="default",
            header_row=1,
            column_mapping={
                "code_col": "A", "name_col": "B", "unit_col": "C",
                "qty_col": "D", "unit_price_col": "E", "total_price_col": "F",
            },
        )
        s.add(rule)
        await s.flush()
        b = Bidder(name="B_ex", project_id=p.id, parse_status="priced")
        s.add(b)
        await s.flush()
        for it in items:
            s.add(PriceItem(
                bidder_id=b.id,
                price_parsing_rule_id=rule.id,
                sheet_name=it.get("sheet_name", "s1"),
                row_index=it.get("row_index", 1),
                item_code=it.get("item_code"),
                item_name=it.get("item_name"),
                unit=it.get("unit"),
                quantity=it.get("quantity"),
                unit_price=it.get("unit_price"),
                total_price=it.get("total_price"),
            ))
        await s.commit()
        return b.id


@pytest.mark.asyncio
async def test_extractor_groups_by_sheet(clean_prices):
    bidder_id = await _seed_bidder_with_items([
        {"sheet_name": "清单表", "row_index": 1, "item_name": "钢筋",
         "unit_price": Decimal("100"), "total_price": Decimal("1000")},
        {"sheet_name": "清单表", "row_index": 2, "item_name": "水泥",
         "unit_price": Decimal("50"), "total_price": Decimal("2500")},
        {"sheet_name": "商务价", "row_index": 1, "item_name": "管理费",
         "unit_price": Decimal("10000"), "total_price": Decimal("10000")},
    ])
    cfg = load_price_config()
    async with async_session() as s:
        grouped = await extract_bidder_prices(s, bidder_id, cfg)
    assert set(grouped.keys()) == {"清单表", "商务价"}
    assert len(grouped["清单表"]) == 2
    assert len(grouped["商务价"]) == 1
    # 预计算字段验证
    r = grouped["清单表"][0]
    assert r["item_name_norm"] == "钢筋"
    assert r["tail_key"] == ("000", 4)  # 1000 → tail "000", int_len 4
    assert r["total_price_float"] == 1000.0


@pytest.mark.asyncio
async def test_extractor_empty_bidder(clean_prices):
    async with async_session() as s:
        u = User(username="u_e", password_hash="x", role="reviewer")
        s.add(u)
        await s.flush()
        p = Project(name="P_e", owner_id=u.id)
        s.add(p)
        await s.flush()
        b = Bidder(name="B_e", project_id=p.id)
        s.add(b)
        await s.commit()
        bidder_id = b.id
    async with async_session() as s:
        grouped = await extract_bidder_prices(s, bidder_id, load_price_config())
    assert grouped == {}


@pytest.mark.asyncio
async def test_extractor_max_rows_limit(clean_prices):
    items = [{"sheet_name": "s", "row_index": i,
              "item_name": f"x{i}",
              "total_price": Decimal(str(100 + i))} for i in range(20)]
    bidder_id = await _seed_bidder_with_items(items)
    # 自定义 cfg: max_rows_per_bidder=5
    base = load_price_config()
    cfg = PriceConfig(
        tail=base.tail, amount_pattern=base.amount_pattern,
        item_list=base.item_list, series=base.series, scorer=base.scorer,
        max_rows_per_bidder=5,
    )
    async with async_session() as s:
        grouped = await extract_bidder_prices(s, bidder_id, cfg)
    flat = flatten_rows(grouped)
    assert len(flat) == 5


@pytest.mark.asyncio
async def test_extractor_null_fields(clean_prices):
    bidder_id = await _seed_bidder_with_items([
        {"sheet_name": "s", "row_index": 1,
         "item_name": None, "unit_price": None, "total_price": None},
    ])
    async with async_session() as s:
        grouped = await extract_bidder_prices(s, bidder_id, load_price_config())
    r = grouped["s"][0]
    assert r["item_name_norm"] is None
    assert r["tail_key"] is None
    assert r["total_price_float"] is None
