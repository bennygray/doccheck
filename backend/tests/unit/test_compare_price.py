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


def _make_rule(rule_id=1, project_id=1, sheets_config=None):
    """Mock PriceParsingRule with sheets_config (default: 1 main sheet 'Sheet1')."""
    class FR:
        pass
    r = FR()
    r.id = rule_id
    r.project_id = project_id
    if sheets_config is None:
        sheets_config = [{"sheet_name": "Sheet1", "sheet_role": "main"}]
    r.sheets_config = sheets_config
    return r


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
            _db_result([_make_rule()]),  # fix-multi-sheet: rules for sheet_role filter
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
            _db_result([_make_rule()]),
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
            _db_result([_make_rule()]),
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
            _db_result([_make_rule()]),
        ])

        user = AsyncMock()
        resp = await compare_price(
            project_id=1, version=None,
            session=mock_session, user=user,
        )

    assert resp.items[0].has_anomaly is True


# ── fix-multi-sheet-price-double-count: sheet_role 过滤场景 ─────────


@pytest.mark.asyncio
async def test_compare_price_excludes_breakdown_from_total():
    """监理标:主表 + 明细分解 sheet 都入库,但底部"总报价"只 SUM main sheet。

    主表 1 行(456000)+ 明细 5 行(SUM 456000)= 7 行入 price_items;
    rule.sheets_config: [main, breakdown] →
      - 主体行展示所有 7 行(单价 cell)
      - 底部"总报价" SUM 仅 main sheet=456000(不是 912000)
    """
    from app.api.routes.compare import compare_price

    bidders = [_make_bidder(1, "供应商A")]
    items = [
        # main sheet "报价表"
        _make_pi(1, "委托监理", 456000, 456000, 0, sheet="报价表"),
        # breakdown sheet "管理人员单价表"(明细 5 行,SUM=456000)
        _make_pi(1, "总监理", 25000, 150000, 0, sheet="管理人员单价表"),
        _make_pi(1, "专业监理土建", 15000, 90000, 1, sheet="管理人员单价表"),
        _make_pi(1, "专业监理机电", 15000, 60000, 2, sheet="管理人员单价表"),
        _make_pi(1, "安全监理", 15000, 90000, 3, sheet="管理人员单价表"),
        _make_pi(1, "监理员", 11000, 66000, 4, sheet="管理人员单价表"),
    ]
    rule = _make_rule(sheets_config=[
        {"sheet_name": "报价表", "sheet_role": "main"},
        {"sheet_name": "管理人员单价表", "sheet_role": "breakdown"},
    ])

    mock_session = AsyncMock()
    with patch("app.api.routes.compare._visible_project", new_callable=AsyncMock):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result(bidders),
            _db_result(items),
            _db_result([rule]),
        ])
        resp = await compare_price(
            project_id=1, version=None,
            session=mock_session, user=AsyncMock(),
        )

    # 主体仍展示所有 6 个 item(每行一个 unique item_name)
    assert len(resp.items) == 6
    # 底部"总报价"仅 SUM main sheet=456000(不是 912000 双重)
    assert resp.totals[0].total_price == 456000.0


@pytest.mark.asyncio
async def test_compare_price_backward_compat_missing_sheet_role():
    """老数据:rule.sheets_config 缺 sheet_role 字段 → 默认 main → 全部 SUM(行为同改前)。"""
    from app.api.routes.compare import compare_price

    bidders = [_make_bidder(1, "A")]
    items = [
        _make_pi(1, "item1", 100, 1000, 0, sheet="Sheet1"),
        _make_pi(1, "item2", 200, 2000, 1, sheet="Sheet1"),
    ]
    # 老数据:无 sheet_role
    rule = _make_rule(sheets_config=[{"sheet_name": "Sheet1"}])

    mock_session = AsyncMock()
    with patch("app.api.routes.compare._visible_project", new_callable=AsyncMock):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result(bidders),
            _db_result(items),
            _db_result([rule]),
        ])
        resp = await compare_price(
            project_id=1, version=None,
            session=mock_session, user=AsyncMock(),
        )

    # 缺字段 → 默认 main → SUM 全部=3000(backward compat)
    assert resp.totals[0].total_price == 3000.0

