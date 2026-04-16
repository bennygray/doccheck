"""L1 — C16 compare/price endpoint 单元测试。

- 正常报价矩阵(3 bidder × N items)
- 无报价投标人 → null 单元格
- 空项目(无 bidder)
- mean=0 边界
- 偏差 <1% → has_anomaly=True
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.compare import PriceCompareResponse


def _db_result(scalars_list):
    result = MagicMock()
    result.scalars.return_value.all.return_value = scalars_list
    return result


def _make_bidder(bid_id, name, project_id=1):
    class FB:
        pass

    b = FB()
    b.id = bid_id
    b.name = name
    b.project_id = project_id
    b.deleted_at = None
    return b


def _make_pi(bidder_id, item_name, unit_price, total_price=None, row_index=0, sheet="Sheet1"):
    class FP:
        pass

    pi = FP()
    pi.id = bidder_id * 1000 + row_index
    pi.bidder_id = bidder_id
    pi.item_name = item_name
    pi.unit = "个"
    pi.unit_price = Decimal(str(unit_price)) if unit_price is not None else None
    pi.total_price = Decimal(str(total_price)) if total_price is not None else None
    pi.sheet_name = sheet
    pi.row_index = row_index
    pi.price_parsing_rule_id = 1
    return pi


@pytest.mark.asyncio
async def test_price_compare_normal():
    """3 个 bidder,2 个报价项,计算均价偏差。"""
    from app.api.routes.compare import compare_price

    bidders = [_make_bidder(1, "A"), _make_bidder(2, "B"), _make_bidder(3, "C")]
    items = [
        _make_pi(1, "水泥", 100, 1000, 0),
        _make_pi(2, "水泥", 100, 1000, 0),
        _make_pi(3, "水泥", 100, 1000, 0),
        _make_pi(1, "钢筋", 200, 2000, 1),
        _make_pi(2, "钢筋", 300, 3000, 1),
        _make_pi(3, "钢筋", 250, 2500, 1),
    ]

    mock_session = AsyncMock()

    with patch("app.api.routes.compare._visible_project", new_callable=AsyncMock):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result(bidders),
            _db_result(items),
        ])

        user = AsyncMock()
        resp = await compare_price(
            project_id=1, version=None,
            session=mock_session, user=user,
        )

    assert isinstance(resp, PriceCompareResponse)
    assert len(resp.bidders) == 3
    assert len(resp.items) == 2

    cement = resp.items[0]
    assert cement.item_name == "水泥"
    assert cement.has_anomaly is True
    for cell in cement.cells:
        assert cell.deviation_pct == 0.0

    assert len(resp.totals) == 3
    assert resp.totals[0].total_price == 3000.0
    assert resp.totals[1].total_price == 4000.0


@pytest.mark.asyncio
async def test_price_compare_no_price_bidder():
    """某 bidder 无报价 → 所有单元格 null。"""
    from app.api.routes.compare import compare_price

    bidders = [_make_bidder(1, "A"), _make_bidder(2, "B")]
    items = [_make_pi(1, "水泥", 100, 500, 0)]

    mock_session = AsyncMock()

    with patch("app.api.routes.compare._visible_project", new_callable=AsyncMock):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result(bidders),
            _db_result(items),
        ])

        user = AsyncMock()
        resp = await compare_price(
            project_id=1, version=None,
            session=mock_session, user=user,
        )

    assert len(resp.items) == 1
    b_cell = [c for c in resp.items[0].cells if c.bidder_id == 2][0]
    assert b_cell.unit_price is None
    assert b_cell.deviation_pct is None


@pytest.mark.asyncio
async def test_price_compare_empty_project():
    """无 bidder → 空响应。"""
    from app.api.routes.compare import compare_price

    mock_session = AsyncMock()

    with patch("app.api.routes.compare._visible_project", new_callable=AsyncMock):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result([]),
        ])

        user = AsyncMock()
        resp = await compare_price(
            project_id=1, version=None,
            session=mock_session, user=user,
        )

    assert resp.bidders == []
    assert resp.items == []
    assert resp.totals == []


@pytest.mark.asyncio
async def test_price_compare_mean_zero():
    """unit_price 全为 0 → mean=0,deviation=None。"""
    from app.api.routes.compare import compare_price

    bidders = [_make_bidder(1, "A"), _make_bidder(2, "B")]
    items = [
        _make_pi(1, "免费项", 0, 0, 0),
        _make_pi(2, "免费项", 0, 0, 0),
    ]

    mock_session = AsyncMock()

    with patch("app.api.routes.compare._visible_project", new_callable=AsyncMock):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result(bidders),
            _db_result(items),
        ])

        user = AsyncMock()
        resp = await compare_price(
            project_id=1, version=None,
            session=mock_session, user=user,
        )

    row = resp.items[0]
    assert row.mean_unit_price == 0.0
    for cell in row.cells:
        assert cell.deviation_pct is None


@pytest.mark.asyncio
async def test_price_compare_anomaly_flag():
    """偏差 <1% → has_anomaly=True。"""
    from app.api.routes.compare import compare_price

    bidders = [_make_bidder(1, "A"), _make_bidder(2, "B")]
    items = [
        _make_pi(1, "item1", 100, 100, 0),
        _make_pi(2, "item1", 100.5, 100.5, 0),
    ]

    mock_session = AsyncMock()

    with patch("app.api.routes.compare._visible_project", new_callable=AsyncMock):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result(bidders),
            _db_result(items),
        ])

        user = AsyncMock()
        resp = await compare_price(
            project_id=1, version=None,
            session=mock_session, user=user,
        )

    assert resp.items[0].has_anomaly is True
