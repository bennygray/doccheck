"""L1 - anomaly_impl/extractor (C12)"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project
from app.models.user import User
from app.services.detect.agents.anomaly_impl.config import AnomalyConfig
from app.services.detect.agents.anomaly_impl.extractor import (
    aggregate_bidder_totals,
)

pytestmark = pytest.mark.asyncio


def _cfg(max_bidders: int = 50) -> AnomalyConfig:
    return AnomalyConfig(
        enabled=True,
        min_sample_size=3,
        deviation_threshold=0.30,
        direction="low",
        baseline_enabled=False,
        max_bidders=max_bidders,
        weight=1.0,
    )


@pytest_asyncio.fixture
async def clean_tables():
    async with async_session() as s:
        await s.execute(delete(PriceItem))
        await s.execute(delete(PriceParsingRule))
        await s.execute(delete(BidDocument))
        await s.execute(delete(Bidder))
        await s.execute(delete(Project))
        await s.execute(delete(User))
        await s.commit()
    yield
    async with async_session() as s:
        await s.execute(delete(PriceItem))
        await s.execute(delete(PriceParsingRule))
        await s.execute(delete(BidDocument))
        await s.execute(delete(Bidder))
        await s.execute(delete(Project))
        await s.execute(delete(User))
        await s.commit()


async def _seed_project(bidder_totals: list[tuple[str, list[Decimal]]]) -> int:
    """建一个 project + 多个 bidder + 每家对应的 price_items 列表。

    bidder_totals: [(bidder_name, [price1, price2, ...])] — 每 bidder 的 price_items。
    返回 project_id。
    """
    async with async_session() as s:
        user = User(
            username=f"ex_{id(s)}",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        s.add(user)
        await s.flush()
        project = Project(name="PA_proj", owner_id=user.id)
        s.add(project)
        await s.flush()

        # PriceParsingRule 是 project 级(非 document 级),共享
        rule = PriceParsingRule(
            project_id=project.id,
            sheet_name="报价明细",
            header_row=1,
            column_mapping={
                "code_col": 0,
                "name_col": 1,
                "unit_col": 2,
                "qty_col": 3,
                "unit_price_col": 4,
                "total_price_col": 5,
            },
            status="confirmed",
        )
        s.add(rule)
        await s.flush()

        for name, prices in bidder_totals:
            bidder = Bidder(
                name=name,
                project_id=project.id,
                parse_status="extracted",
            )
            s.add(bidder)
            await s.flush()
            for i, price in enumerate(prices):
                pi = PriceItem(
                    bidder_id=bidder.id,
                    price_parsing_rule_id=rule.id,
                    sheet_name="报价明细",
                    row_index=i,
                    item_name=f"项{i}",
                    total_price=price,
                )
                s.add(pi)
            await s.flush()
        await s.commit()
        return project.id


async def test_aggregate_5_bidders(clean_tables):
    pid = await _seed_project(
        [
            ("A", [Decimal("40"), Decimal("60")]),  # 100
            ("B", [Decimal("105")]),
            ("C", [Decimal("98")]),
            ("D", [Decimal("70")]),
            ("E", [Decimal("102")]),
        ]
    )
    async with async_session() as s:
        summaries = await aggregate_bidder_totals(s, pid, _cfg())
    totals = [s_["total_price"] for s_ in summaries]
    assert totals == [100.0, 105.0, 98.0, 70.0, 102.0]


async def test_aggregate_bidder_id_ascending(clean_tables):
    pid = await _seed_project(
        [
            ("Z", [Decimal("1")]),
            ("A", [Decimal("2")]),
            ("M", [Decimal("3")]),
        ]
    )
    async with async_session() as s:
        summaries = await aggregate_bidder_totals(s, pid, _cfg())
    ids = [s_["bidder_id"] for s_ in summaries]
    assert ids == sorted(ids)


async def test_aggregate_skips_bidders_without_price_items(clean_tables):
    pid = await _seed_project(
        [
            ("A", [Decimal("100")]),
            ("B", []),  # 无 price_items
            ("C", [Decimal("98")]),
        ]
    )
    async with async_session() as s:
        summaries = await aggregate_bidder_totals(s, pid, _cfg())
    assert len(summaries) == 2
    names = {s_["bidder_name"] for s_ in summaries}
    assert names == {"A", "C"}


async def test_max_bidders_truncation(clean_tables):
    # 建 5 家,max_bidders=3 → 取前 3(bidder_id 升序)
    pid = await _seed_project(
        [(f"B{i}", [Decimal("100")]) for i in range(5)]
    )
    async with async_session() as s:
        summaries = await aggregate_bidder_totals(s, pid, _cfg(max_bidders=3))
    assert len(summaries) == 3


async def test_aggregate_soft_deleted_bidder_excluded(clean_tables):
    """软删 bidder 不参与聚合。"""
    from datetime import datetime, timezone

    pid = await _seed_project(
        [
            ("A", [Decimal("100")]),
            ("B", [Decimal("105")]),
            ("C", [Decimal("98")]),
        ]
    )
    async with async_session() as s:
        # 软删 B
        bidders = (await s.execute(
            __import__("sqlalchemy").select(Bidder).where(
                Bidder.project_id == pid, Bidder.name == "B"
            )
        )).scalars().all()
        for b in bidders:
            b.deleted_at = datetime.now(timezone.utc)
        await s.commit()

        summaries = await aggregate_bidder_totals(s, pid, _cfg())
    assert len(summaries) == 2
    names = {s_["bidder_name"] for s_ in summaries}
    assert names == {"A", "C"}
