"""L1 - error_consistency preflight + bidder_has_identity_info helper (C13)"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.detect.agents._preflight_helpers import (
    bidder_has_identity_info,
)
from app.services.detect.agents.error_consistency import preflight
from app.services.detect.context import AgentContext


def _bidder(bid: int, info=None):
    return SimpleNamespace(id=bid, name=f"b{bid}", identity_info=info)


def _ctx(bidders) -> AgentContext:
    return AgentContext(
        project_id=1,
        version=1,
        agent_task=SimpleNamespace(),  # type: ignore[arg-type]
        bidder_a=None,
        bidder_b=None,
        all_bidders=bidders,
        session=None,
    )


def test_helper_none_returns_false() -> None:
    assert bidder_has_identity_info(_bidder(1, None)) is False


def test_helper_empty_dict_returns_false() -> None:
    assert bidder_has_identity_info(_bidder(1, {})) is False


def test_helper_non_dict_returns_false() -> None:
    assert bidder_has_identity_info(_bidder(1, "not a dict")) is False


def test_helper_with_value_returns_true() -> None:
    assert bidder_has_identity_info(
        _bidder(1, {"company_name": "甲"})
    ) is True


@pytest.mark.asyncio
async def test_preflight_skip_lt_2_bidders() -> None:
    result = await preflight(_ctx([_bidder(1, {"company_name": "x"})]))
    assert result.status == "skip"


@pytest.mark.asyncio
async def test_preflight_ok_all_have_identity() -> None:
    bidders = [
        _bidder(1, {"company_name": "甲"}),
        _bidder(2, {"company_name": "乙"}),
    ]
    result = await preflight(_ctx(bidders))
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_preflight_downgrade_any_missing() -> None:
    """任一 bidder 缺 → downgrade(贴 spec §F-DA-02 原语义)。"""
    bidders = [
        _bidder(1, {"company_name": "甲"}),
        _bidder(2, None),
    ]
    result = await preflight(_ctx(bidders))
    assert result.status == "downgrade"


@pytest.mark.asyncio
async def test_preflight_downgrade_all_missing() -> None:
    bidders = [_bidder(1, None), _bidder(2, None)]
    result = await preflight(_ctx(bidders))
    assert result.status == "downgrade"
    assert "降级" in (result.reason or "")
