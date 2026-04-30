"""L1 - baseline_resolver L3 警示 path 单测 (detect-tender-baseline §2)

覆盖 spec ADD Req "baseline_resolver 三级降级判定" L3 scenarios:
- 无 tender + ≤2 投标方 → warnings='baseline_unavailable_low_bidder_count'
- excluded_pair_ids=空集(不剔除任何 PC)
- baseline_source='none'(L3 不抑制 ironclad,基线缺失 ≠ 信号无效)
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.detect import baseline_resolver


def _pc(pc_id: int, dim: str, a_id: int, b_id: int):
    return SimpleNamespace(
        id=pc_id,
        dimension=dim,
        bidder_a_id=a_id,
        bidder_b_id=b_id,
        score=Decimal("80"),
        is_ironclad=False,
        evidence_json={},
    )


class _FakeSession:
    pass


@pytest.mark.asyncio
async def test_resolve_baseline_l3_two_bidders_warns(monkeypatch):
    """无 tender + 2 投标方 → warnings 含 baseline_unavailable_low_bidder_count。"""
    pc = _pc(1, "text_similarity", 10, 20)

    async def _fake_tender_segs(session, pid):
        return set()

    async def _bidder_count(session, pid):
        return 2

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_segment_hashes", _fake_tender_segs
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _bidder_count
    )

    res = await baseline_resolver.resolve_baseline(
        _FakeSession(), 1, "text_similarity", [pc]
    )
    assert res.excluded_pair_ids == set()
    assert res.baseline_source == "none"
    assert (
        baseline_resolver.WARN_LOW_BIDDER in res.warnings
    ), f"warnings={res.warnings}"


@pytest.mark.asyncio
async def test_resolve_baseline_l3_one_bidder_warns(monkeypatch):
    """1 投标方场景同样触发警示(虽实际无 PC pair 但接口契约一致)。"""

    async def _fake_tender_segs(session, pid):
        return set()

    async def _bidder_count(session, pid):
        return 1

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_segment_hashes", _fake_tender_segs
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _bidder_count
    )

    res = await baseline_resolver.resolve_baseline(
        _FakeSession(), 1, "text_similarity", []
    )
    assert res.excluded_pair_ids == set()
    assert res.baseline_source == "none"
    assert baseline_resolver.WARN_LOW_BIDDER in res.warnings


@pytest.mark.asyncio
async def test_resolve_baseline_l3_no_warning_when_three_plus_bidders(monkeypatch):
    """3 bidders 无 tender 无共识 → baseline_source='none' 但 warnings 不含 L3 警示。"""
    pc = _pc(1, "text_similarity", 10, 20)

    async def _fake_tender_segs(session, pid):
        return set()

    async def _fake_segs_by_role(session, pid):
        return {
            10: {"technical": {"h1"}},
            20: {"technical": {"h2"}},
            30: {"technical": {"h3"}},
        }  # 无共识

    async def _bidder_count(session, pid):
        return 3

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_segment_hashes", _fake_tender_segs
    )
    monkeypatch.setattr(
        baseline_resolver,
        "_load_bidder_segment_hashes_by_role",
        _fake_segs_by_role,
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _bidder_count
    )

    res = await baseline_resolver.resolve_baseline(
        _FakeSession(), 1, "text_similarity", [pc]
    )
    assert res.warnings == []
    assert res.baseline_source == "none"


@pytest.mark.asyncio
async def test_resolve_baseline_l3_tender_overrides_warning(monkeypatch):
    """≤2 投标方 + 有 tender 命中 → 走 L1,MUST NOT 出 L3 警示。"""
    pc = _pc(1, "text_similarity", 10, 20)

    async def _fake_tender_segs(session, pid):
        return {"h1"}

    async def _fake_bidder_pair(session, pid):
        return {10: {"h1"}, 20: {"h1"}}

    async def _bidder_count(session, pid):
        return 2

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_segment_hashes", _fake_tender_segs
    )
    monkeypatch.setattr(
        baseline_resolver, "_load_bidder_pair_segment_hashes", _fake_bidder_pair
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _bidder_count
    )

    res = await baseline_resolver.resolve_baseline(
        _FakeSession(), 1, "text_similarity", [pc]
    )
    assert res.excluded_pair_ids == {1}
    assert res.baseline_source == "tender"
    assert baseline_resolver.WARN_LOW_BIDDER not in res.warnings
