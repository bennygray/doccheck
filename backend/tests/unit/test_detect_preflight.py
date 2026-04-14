"""L1 - Agent preflight 单元测试 (C6 §9.2)

关注点:
- skip 场景(text_similarity 缺文档)
- downgrade 场景(error_consistency identity_info 空)
- preflight 异常视为 skip(engine 层包容)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.detect.agents.error_consistency import (
    preflight as ec_preflight,
)
from app.services.detect.agents.text_similarity import (
    preflight as ts_preflight,
)
from app.services.detect.context import AgentContext, PreflightResult


def _make_bidder(id: int, name: str = "B", identity: dict | None = None):
    return SimpleNamespace(id=id, name=name, identity_info=identity)


def _make_ctx(bidder_a=None, bidder_b=None, all_bidders=None, session=None):
    return AgentContext(
        project_id=1,
        version=1,
        agent_task=SimpleNamespace(),
        bidder_a=bidder_a,
        bidder_b=bidder_b,
        all_bidders=all_bidders or [],
        session=session,
    )


# ---------- text_similarity ----------

@pytest.mark.asyncio
async def test_text_similarity_skip_when_missing_session():
    ctx = _make_ctx(bidder_a=_make_bidder(1), bidder_b=_make_bidder(2))
    # session 为 None → skip
    result = await ts_preflight(ctx)
    assert result.status == "skip"
    assert "文档" in (result.reason or "")


@pytest.mark.asyncio
async def test_text_similarity_ok_when_shared_role():
    session = AsyncMock()
    # bidders_share_any_role 返 True
    from app.services.detect.agents import text_similarity as mod

    original = mod.bidders_share_any_role
    mod.bidders_share_any_role = AsyncMock(return_value=True)
    try:
        ctx = _make_ctx(
            bidder_a=_make_bidder(1),
            bidder_b=_make_bidder(2),
            session=session,
        )
        result = await ts_preflight(ctx)
        assert result.status == "ok"
    finally:
        mod.bidders_share_any_role = original


# ---------- error_consistency(downgrade)----------

@pytest.mark.asyncio
async def test_error_consistency_downgrade_when_identity_missing():
    b1 = _make_bidder(1, identity={"idcard": "..."})
    b2 = _make_bidder(2, identity=None)  # 缺
    ctx = _make_ctx(all_bidders=[b1, b2])
    result = await ec_preflight(ctx)
    assert result.status == "downgrade"
    assert "降级" in (result.reason or "")


@pytest.mark.asyncio
async def test_error_consistency_ok_when_all_identity_present():
    b1 = _make_bidder(1, identity={"x": 1})
    b2 = _make_bidder(2, identity={"x": 2})
    ctx = _make_ctx(all_bidders=[b1, b2])
    result = await ec_preflight(ctx)
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_error_consistency_skip_when_less_than_2_bidders():
    ctx = _make_ctx(all_bidders=[_make_bidder(1)])
    result = await ec_preflight(ctx)
    assert result.status == "skip"


# ---------- PreflightResult 数据类 ----------

def test_preflight_result_defaults():
    r = PreflightResult("ok")
    assert r.status == "ok"
    assert r.reason is None
