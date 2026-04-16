"""L1 - error_consistency.run() (C13)"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class _FakeSession:
    """最小 stub session:add() 收集调用,flush() 异步无操作。"""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

from app.services.detect.agents import error_consistency
from app.services.detect.agents.error_impl.models import (
    LLMJudgment,
    SuspiciousSegment,
)
from app.services.detect.context import AgentContext


def _bidder(bid: int, info=None):
    return SimpleNamespace(id=bid, name=f"b{bid}", identity_info=info)


def _ctx(bidders, *, downgrade=False, session=None, llm=None) -> AgentContext:
    return AgentContext(
        project_id=1,
        version=1,
        agent_task=SimpleNamespace(),  # type: ignore[arg-type]
        bidder_a=None,
        bidder_b=None,
        all_bidders=bidders,
        session=session,
        llm_provider=llm,
        downgrade=downgrade,
    )


@pytest.mark.asyncio
async def test_disabled_early_return(monkeypatch) -> None:
    monkeypatch.setenv("ERROR_CONSISTENCY_ENABLED", "false")
    bidders = [_bidder(1, {"company_name": "甲建设"}),
               _bidder(2, {"company_name": "乙建设"})]
    result = await error_consistency.run(_ctx(bidders))
    assert result.score == 0.0
    assert result.evidence_json["enabled"] is False


@pytest.mark.asyncio
async def test_iron_evidence_hit(monkeypatch) -> None:
    monkeypatch.delenv("ERROR_CONSISTENCY_ENABLED", raising=False)

    async def fake_search(_session, _a, _b, kw_a, kw_b, _cfg):
        return (
            [SuspiciousSegment(
                paragraph_text="hit",
                doc_id=1, doc_role="t", position="body",
                matched_keywords=["x"], source_bidder_id=1,
            )],
            False, 1,
        )

    async def fake_call(_provider, _segs, _a, _b, _cfg) -> LLMJudgment:
        return LLMJudgment(
            is_cross_contamination=True,
            direct_evidence=True,
            confidence=0.9,
            evidence=[],
        )

    monkeypatch.setattr(
        "app.services.detect.agents.error_consistency.search", fake_search
    )
    monkeypatch.setattr(
        "app.services.detect.agents.error_consistency.call_l5", fake_call
    )

    bidders = [_bidder(1, {"company_name": "甲建设"}),
               _bidder(2, {"company_name": "乙建设"})]
    fake_session = object()
    result = await error_consistency.run(_ctx(bidders, session=_FakeSession()))
    assert result.evidence_json["has_iron_evidence"] is True
    pair_results = result.evidence_json["pair_results"]
    assert pair_results[0]["is_iron_evidence"] is True


@pytest.mark.asyncio
async def test_non_iron_hit(monkeypatch) -> None:
    async def fake_search(*args, **kwargs):
        return (
            [SuspiciousSegment(
                paragraph_text="hit", doc_id=1, doc_role="t",
                position="body", matched_keywords=["x"], source_bidder_id=1,
            )],
            False, 1,
        )

    async def fake_call(*args, **kwargs):
        return LLMJudgment(
            is_cross_contamination=True,
            direct_evidence=False,
            confidence=0.5,
            evidence=[],
        )

    monkeypatch.setattr(
        "app.services.detect.agents.error_consistency.search", fake_search
    )
    monkeypatch.setattr(
        "app.services.detect.agents.error_consistency.call_l5", fake_call
    )

    bidders = [_bidder(1, {"company_name": "甲建设"}),
               _bidder(2, {"company_name": "乙建设"})]
    result = await error_consistency.run(_ctx(bidders, session=_FakeSession()))
    assert result.evidence_json["has_iron_evidence"] is False


@pytest.mark.asyncio
async def test_downgrade_mode_forces_no_iron(monkeypatch) -> None:
    async def fake_search(*args, **kwargs):
        return (
            [SuspiciousSegment(
                paragraph_text="hit", doc_id=1, doc_role="t",
                position="body", matched_keywords=["x"], source_bidder_id=1,
            )],
            False, 1,
        )

    async def fake_call(*args, **kwargs):
        return LLMJudgment(
            is_cross_contamination=True,
            direct_evidence=True,  # 即使 LLM 返铁证
            confidence=0.9,
            evidence=[],
        )

    monkeypatch.setattr(
        "app.services.detect.agents.error_consistency.search", fake_search
    )
    monkeypatch.setattr(
        "app.services.detect.agents.error_consistency.call_l5", fake_call
    )

    bidders = [_bidder(1, None), _bidder(2, None)]
    result = await error_consistency.run(
        _ctx(bidders, downgrade=True, session=_FakeSession())
    )
    # 降级模式强制 no iron
    assert result.evidence_json["has_iron_evidence"] is False
    assert result.evidence_json["downgrade_mode"] is True


@pytest.mark.asyncio
async def test_llm_failure_no_iron(monkeypatch) -> None:
    async def fake_search(*args, **kwargs):
        return (
            [SuspiciousSegment(
                paragraph_text="hit", doc_id=1, doc_role="t",
                position="body", matched_keywords=["x"], source_bidder_id=1,
            )],
            False, 1,
        )

    async def fake_call(*args, **kwargs):
        return None  # LLM 失败

    monkeypatch.setattr(
        "app.services.detect.agents.error_consistency.search", fake_search
    )
    monkeypatch.setattr(
        "app.services.detect.agents.error_consistency.call_l5", fake_call
    )

    bidders = [_bidder(1, {"company_name": "甲建设"}),
               _bidder(2, {"company_name": "乙建设"})]
    result = await error_consistency.run(_ctx(bidders, session=_FakeSession()))
    assert result.evidence_json["has_iron_evidence"] is False
    pair = result.evidence_json["pair_results"][0]
    assert pair["llm_failed"] is True
    assert pair["is_iron_evidence"] is False


@pytest.mark.asyncio
async def test_no_extractable_keywords_skip(monkeypatch) -> None:
    bidders = [_bidder(1, {"company_name": "甲"}),  # len=1 被过滤
               _bidder(2, {"company_name": "乙"})]
    result = await error_consistency.run(_ctx(bidders, session=_FakeSession()))
    assert result.evidence_json["skip_reason"] == "no_extractable_keywords"
    assert result.score == 0.0


@pytest.mark.asyncio
async def test_invalid_context_writes_oa(monkeypatch) -> None:
    """DEF-OA 3.4: bidders<2 时仍写 OA 行(score=0, skip_reason)。"""
    monkeypatch.delenv("ERROR_CONSISTENCY_ENABLED", raising=False)
    session = _FakeSession()
    bidders = [_bidder(1, {"company_name": "甲建设"})]  # 只有 1 个
    result = await error_consistency.run(_ctx(bidders, session=session))
    assert result.score == 0.0
    assert result.evidence_json["skip_reason"] == "invalid_context"
    # 验证 OA 行被写入
    from app.models.overall_analysis import OverallAnalysis
    oa_rows = [o for o in session.added if isinstance(o, OverallAnalysis)]
    assert len(oa_rows) == 1
    assert oa_rows[0].dimension == "error_consistency"
    assert float(oa_rows[0].score) == 0.0


@pytest.mark.asyncio
async def test_search_exception_caught(monkeypatch) -> None:
    async def fake_search(*args, **kwargs):
        raise RuntimeError("DB error")

    monkeypatch.setattr(
        "app.services.detect.agents.error_consistency.search", fake_search
    )

    bidders = [_bidder(1, {"company_name": "甲建设"}),
               _bidder(2, {"company_name": "乙建设"})]
    result = await error_consistency.run(_ctx(bidders, session=_FakeSession()))
    assert result.score == 0.0
    assert "RuntimeError" in result.evidence_json["error"]
