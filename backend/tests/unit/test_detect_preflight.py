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
async def test_text_similarity_ok_when_shared_role_and_enough_chars(monkeypatch):
    """C7 更新:preflight 在"同角色文档存在"之外追加 total_chars 字数检查。"""
    session = AsyncMock()
    from app.services.detect.agents import text_similarity as mod
    from app.services.detect.agents.text_sim_impl import segmenter

    monkeypatch.setattr(
        mod.segmenter,
        "choose_shared_role",
        AsyncMock(return_value=["technical"]),
    )
    monkeypatch.setattr(
        mod.segmenter,
        "load_paragraphs_for_roles",
        AsyncMock(
            return_value=segmenter.SegmentResult(
                doc_role="technical", doc_id=1, paragraphs=["x" * 600], total_chars=600
            )
        ),
    )

    ctx = _make_ctx(
        bidder_a=_make_bidder(1),
        bidder_b=_make_bidder(2),
        session=session,
    )
    result = await ts_preflight(ctx)
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_text_similarity_skip_when_no_shared_role(monkeypatch):
    session = AsyncMock()
    from app.services.detect.agents import text_similarity as mod

    monkeypatch.setattr(
        mod.segmenter,
        "choose_shared_role",
        AsyncMock(return_value=[]),  # 无共有 role
    )

    ctx = _make_ctx(
        bidder_a=_make_bidder(1),
        bidder_b=_make_bidder(2),
        session=session,
    )
    result = await ts_preflight(ctx)
    assert result.status == "skip"
    assert result.reason == "缺少可对比文档"


@pytest.mark.asyncio
async def test_text_similarity_skip_when_doc_too_short(monkeypatch):
    """C7 新增:任一侧 total_chars < MIN_DOC_CHARS → skip '文档过短无法对比'。"""
    session = AsyncMock()
    from app.services.detect.agents import text_similarity as mod
    from app.services.detect.agents.text_sim_impl import segmenter

    monkeypatch.setattr(
        mod.segmenter,
        "choose_shared_role",
        AsyncMock(return_value=["technical"]),
    )
    # 第一次调返超短(a 侧),第二次调返正常(b 侧) — mode: 单边短也 skip
    short = segmenter.SegmentResult(
        doc_role="technical", doc_id=1, paragraphs=["短"], total_chars=10
    )
    long_ = segmenter.SegmentResult(
        doc_role="technical", doc_id=2, paragraphs=["x" * 600], total_chars=600
    )
    monkeypatch.setattr(
        mod.segmenter,
        "load_paragraphs_for_roles",
        AsyncMock(side_effect=[short, long_]),
    )

    ctx = _make_ctx(
        bidder_a=_make_bidder(1),
        bidder_b=_make_bidder(2),
        session=session,
    )
    result = await ts_preflight(ctx)
    assert result.status == "skip"
    assert result.reason == "文档过短无法对比"


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
