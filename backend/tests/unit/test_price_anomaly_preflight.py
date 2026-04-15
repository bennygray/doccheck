"""L1 - price_anomaly preflight + project_has_priced_bidders helper (C12)"""

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
from app.services.detect.agents._preflight_helpers import (
    project_has_priced_bidders,
)
from app.services.detect.agents.price_anomaly import preflight
from app.services.detect.context import AgentContext

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def clean_tables():
    async with async_session() as s:
        await s.execute(delete(PriceItem))
        await s.execute(delete(PriceParsingRule))
        await s.execute(delete(Bidder))
        await s.execute(delete(Project))
        await s.execute(delete(User))
        await s.commit()
    yield
    async with async_session() as s:
        await s.execute(delete(PriceItem))
        await s.execute(delete(PriceParsingRule))
        await s.execute(delete(Bidder))
        await s.execute(delete(Project))
        await s.execute(delete(User))
        await s.commit()


async def _seed(bidder_counts: list[int]) -> int:
    """建 project + bidder + 对应 price_items 数量;返 project_id。

    bidder_counts[i] = 第 i 个 bidder 的 price_items 数(0 = 无 price_items)。
    """
    async with async_session() as s:
        user = User(
            username=f"pf_{id(s)}",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        s.add(user)
        await s.flush()
        project = Project(name="PF_proj", owner_id=user.id)
        s.add(project)
        await s.flush()

        rule = PriceParsingRule(
            project_id=project.id,
            sheet_name="明细",
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

        for i, cnt in enumerate(bidder_counts):
            bidder = Bidder(
                name=f"B{i}",
                project_id=project.id,
                parse_status="extracted",
            )
            s.add(bidder)
            await s.flush()
            for j in range(cnt):
                pi = PriceItem(
                    bidder_id=bidder.id,
                    price_parsing_rule_id=rule.id,
                    sheet_name="明细",
                    row_index=j,
                    total_price=Decimal("100"),
                )
                s.add(pi)
            await s.flush()
        await s.commit()
        return project.id


async def test_helper_3_priced_bidders_ok(clean_tables):
    pid = await _seed([1, 1, 1])  # 3 家各有 price_item
    async with async_session() as s:
        assert await project_has_priced_bidders(s, pid, 3) is True


async def test_helper_only_2_priced_returns_false(clean_tables):
    pid = await _seed([1, 1])
    async with async_session() as s:
        assert await project_has_priced_bidders(s, pid, 3) is False


async def test_helper_bidder_without_price_items_not_counted(clean_tables):
    """3 家 bidder 但 1 家无 price_items → 仅 2 家计入。"""
    pid = await _seed([1, 0, 1])
    async with async_session() as s:
        assert await project_has_priced_bidders(s, pid, 3) is False
        assert await project_has_priced_bidders(s, pid, 2) is True


async def test_helper_min_count_2_edge(clean_tables):
    pid = await _seed([1, 1])
    async with async_session() as s:
        assert await project_has_priced_bidders(s, pid, 2) is True
        assert await project_has_priced_bidders(s, pid, 3) is False


async def test_agent_preflight_ok(clean_tables, monkeypatch):
    monkeypatch.setenv("PRICE_ANOMALY_MIN_SAMPLE_SIZE", "3")
    pid = await _seed([1, 1, 1])
    async with async_session() as s:
        ctx = AgentContext(
            project_id=pid,
            version=1,
            agent_task=None,
            bidder_a=None,
            bidder_b=None,
            all_bidders=[],
            session=s,
        )
        result = await preflight(ctx)
    assert result.status == "ok"


async def test_agent_preflight_skip_sample_insufficient(
    clean_tables, monkeypatch
):
    monkeypatch.setenv("PRICE_ANOMALY_MIN_SAMPLE_SIZE", "3")
    pid = await _seed([1, 1])  # 只有 2 家
    async with async_session() as s:
        ctx = AgentContext(
            project_id=pid,
            version=1,
            agent_task=None,
            bidder_a=None,
            bidder_b=None,
            all_bidders=[],
            session=s,
        )
        result = await preflight(ctx)
    assert result.status == "skip"
    assert "样本数不足" in result.reason


async def test_agent_preflight_no_session_skip():
    ctx = AgentContext(
        project_id=1,
        version=1,
        agent_task=None,
        bidder_a=None,
        bidder_b=None,
        all_bidders=[],
        session=None,
    )
    result = await preflight(ctx)
    assert result.status == "skip"
