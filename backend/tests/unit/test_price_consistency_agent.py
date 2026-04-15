"""L1 - price_consistency Agent run() (C11)"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.detect.agents import price_consistency
from app.services.detect.context import AgentContext


def _make_ctx():
    """AgentContext 不走 DB:session=None → write_pair_comparison_row 静默。"""
    return AgentContext(
        project_id=1,
        version=1,
        agent_task=SimpleNamespace(id=1),
        bidder_a=SimpleNamespace(id=1, name="A"),
        bidder_b=SimpleNamespace(id=2, name="B"),
        all_bidders=[],
        session=None,
    )


def _row(item_name=None, unit_price=None, total_price=None,
         sheet="s1", row_index=1, idx=1):
    """构造 PriceRow."""
    if total_price is None:
        tail_key = None
        total_float = None
    else:
        int_val = int(total_price)
        if int_val < 0:
            tail_key = None
        else:
            int_str = str(int_val)
            tail = int_str[-3:] if len(int_str) >= 3 else int_str.zfill(3)
            tail_key = (tail, len(int_str))
        total_float = float(total_price)
    return {
        "price_item_id": idx,
        "bidder_id": 1,
        "sheet_name": sheet,
        "row_index": row_index,
        "item_name_raw": item_name,
        "item_name_norm": item_name.lower() if item_name else None,
        "unit_price_raw": unit_price,
        "total_price_raw": total_price,
        "total_price_float": total_float,
        "tail_key": tail_key,
    }


@pytest.mark.asyncio
async def test_algorithm_marker_on_match(monkeypatch):
    """命中场景:tail 子检测命中 → algorithm=v1, score>0。"""
    grouped_a = {"s1": [_row(item_name=f"x{i}", unit_price=Decimal("100"),
                              total_price=Decimal("880"), row_index=i, idx=i)
                         for i in range(3)]}
    grouped_b = {"s1": [_row(item_name=f"x{i}", unit_price=Decimal("100"),
                              total_price=Decimal("880"), row_index=i, idx=10 + i)
                         for i in range(3)]}
    monkeypatch.setattr(
        price_consistency,
        "extract_bidder_prices",
        AsyncMock(side_effect=[grouped_a, grouped_b]),
    )
    result = await price_consistency.run(_make_ctx())
    assert result.evidence_json["algorithm"] == "price_consistency_v1"
    assert result.evidence_json["enabled"] is True
    assert result.score > 0
    assert "tail" in result.evidence_json["participating_subdims"]


@pytest.mark.asyncio
async def test_agent_skip_sentinel_when_all_subdims_skip(monkeypatch):
    """4 子检测全 skip(无数据)→ Agent 级 skip 哨兵。"""
    grouped_a: dict = {}
    grouped_b: dict = {}
    monkeypatch.setattr(
        price_consistency,
        "extract_bidder_prices",
        AsyncMock(side_effect=[grouped_a, grouped_b]),
    )
    result = await price_consistency.run(_make_ctx())
    assert result.score == 0.0
    assert result.evidence_json["enabled"] is False
    assert result.evidence_json["participating_subdims"] == []
    # subdims 仍含 4 子检测 stub
    assert set(result.evidence_json["subdims"].keys()) == {
        "tail", "amount_pattern", "item_list", "series"
    }


@pytest.mark.asyncio
async def test_single_flag_disabled_others_still_run(monkeypatch):
    """关闭 series 单 flag,tail 等仍正常跑。"""
    grouped_a = {"s1": [_row(item_name=f"x{i}", unit_price=Decimal("100"),
                              total_price=Decimal("100"), row_index=i, idx=i)
                         for i in range(5)]}
    grouped_b = {"s1": [_row(item_name=f"x{i}", unit_price=Decimal("100"),
                              total_price=Decimal("100"), row_index=i, idx=10 + i)
                         for i in range(5)]}
    monkeypatch.setattr(
        price_consistency,
        "extract_bidder_prices",
        AsyncMock(side_effect=[grouped_a, grouped_b]),
    )
    monkeypatch.setenv("PRICE_CONSISTENCY_SERIES_ENABLED", "false")
    result = await price_consistency.run(_make_ctx())
    assert result.evidence_json["enabled"] is True
    assert result.evidence_json["subdims"]["series"]["enabled"] is False
    # series 不在 participating
    assert "series" not in result.evidence_json["participating_subdims"]
    # tail/amount_pattern/item_list 仍参与
    assert "tail" in result.evidence_json["participating_subdims"]


@pytest.mark.asyncio
async def test_all_flags_disabled_early_return(monkeypatch):
    """4 flag 全关 → 早返,extractor 不被调用。"""
    ext_mock = AsyncMock()
    monkeypatch.setattr(price_consistency, "extract_bidder_prices", ext_mock)
    monkeypatch.setenv("PRICE_CONSISTENCY_TAIL_ENABLED", "false")
    monkeypatch.setenv("PRICE_CONSISTENCY_AMOUNT_PATTERN_ENABLED", "false")
    monkeypatch.setenv("PRICE_CONSISTENCY_ITEM_LIST_ENABLED", "false")
    monkeypatch.setenv("PRICE_CONSISTENCY_SERIES_ENABLED", "false")
    result = await price_consistency.run(_make_ctx())
    assert result.score == 0.0
    assert result.evidence_json["enabled"] is False
    assert "禁用" in result.summary
    ext_mock.assert_not_called()


@pytest.mark.asyncio
async def test_exception_writes_error_evidence(monkeypatch):
    monkeypatch.setattr(
        price_consistency,
        "extract_bidder_prices",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    result = await price_consistency.run(_make_ctx())
    assert result.score == 0.0
    assert "error" in result.evidence_json
    assert "RuntimeError" in result.evidence_json["error"]
    assert "执行失败" in result.summary


@pytest.mark.asyncio
async def test_series_relation_match(monkeypatch):
    """B = A × 0.95 等比关系 → series 子检测命中。"""
    a_vals = [Decimal("100"), Decimal("200"), Decimal("300"), Decimal("400"), Decimal("500")]
    b_vals = [v * Decimal("0.95") for v in a_vals]
    grouped_a = {"s1": [_row(item_name=f"x{i}", unit_price=a_vals[i],
                              total_price=a_vals[i], row_index=i, idx=i)
                         for i in range(5)]}
    grouped_b = {"s1": [_row(item_name=f"x{i}", unit_price=b_vals[i],
                              total_price=b_vals[i], row_index=i, idx=10 + i)
                         for i in range(5)]}
    monkeypatch.setattr(
        price_consistency,
        "extract_bidder_prices",
        AsyncMock(side_effect=[grouped_a, grouped_b]),
    )
    result = await price_consistency.run(_make_ctx())
    series_ev = result.evidence_json["subdims"]["series"]
    assert series_ev["score"] == 1.0
    assert any(h["mode"] == "ratio" for h in series_ev["hits"])
