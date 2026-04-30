"""L1 - baseline_resolver L1 tender path 单测 (detect-tender-baseline §2)

覆盖 spec ADD Req "baseline_resolver 三级降级判定" L1 scenarios:
- tender hash 命中(全 baseline 命中 PC 进 excluded_pair_ids)
- 部分命中不豁免整 PC(shared 含 non-baseline → 不进)
- L1 优先于投标方数量门槛(≤2 bidders + tender 仍走 L1)
- BOQ 维度仅走 L1(price_consistency / price_anomaly)

策略:monkeypatch DB loader 让纯逻辑可单测;
async DB 流转端到端测试由 L2 e2e 覆盖。
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.detect import baseline_resolver


def _pc(pc_id: int, dim: str, a_id: int, b_id: int, score: float = 80.0):
    return SimpleNamespace(
        id=pc_id,
        dimension=dim,
        bidder_a_id=a_id,
        bidder_b_id=b_id,
        score=Decimal(str(score)),
        is_ironclad=False,
        evidence_json={},
    )


# ============================================================ pure helpers


def test_is_pc_fully_baselined_all_shared_in_tender():
    """shared := a ∩ b 全部 ∈ baseline → fully baselined。"""
    a = {"h1", "h2", "h3"}
    b = {"h1", "h2", "h4"}
    tender = {"h1", "h2", "h5"}
    # shared = {h1, h2},全部 ∈ tender
    assert baseline_resolver._is_pc_fully_baselined(a, b, tender) is True


def test_is_pc_fully_baselined_partial_not_excluded():
    """shared 含 non-baseline → 不豁免整 PC(spec scenario)。"""
    a = {"h1", "h2", "h3"}
    b = {"h1", "h2", "h3"}
    tender = {"h1"}  # 只 h1 是 tender;h2/h3 是 non-baseline shared
    # shared = {h1, h2, h3},仅 h1 ∈ tender → not fully baselined
    assert baseline_resolver._is_pc_fully_baselined(a, b, tender) is False


def test_is_pc_fully_baselined_no_shared_returns_false():
    a = {"h1", "h2"}
    b = {"h3", "h4"}
    tender = {"h1", "h2", "h3", "h4"}
    # shared = ∅ → False(无可判定的 baseline 关联)
    assert baseline_resolver._is_pc_fully_baselined(a, b, tender) is False


def test_is_pc_fully_baselined_empty_baseline_returns_false():
    a = {"h1"}
    b = {"h1"}
    assert baseline_resolver._is_pc_fully_baselined(a, b, set()) is False


def test_build_tender_adjustment_score_zero_iron_false():
    """tender_match 语义:score=0 + is_ironclad=False(spec ADD Req 协同契约)。"""
    pc = _pc(101, "text_similarity", 1, 2, score=85.5)
    pc.is_ironclad = True
    adj = baseline_resolver._build_tender_adjustment(pc, reason="tender_match")
    assert adj["scope"] == "pc"
    assert sorted(adj["pair"]) == [1, 2]
    assert adj["dimension"] == "text_similarity"
    assert adj["raw_score"] == 85.5
    assert adj["adjusted_score"] == 0.0
    assert adj["raw_is_ironclad"] is True
    assert adj["reason"] == "tender_match"
    assert adj["baseline_source"] == "tender"


def test_build_consensus_adjustment_baseline_source_consensus():
    pc = _pc(102, "section_similarity", 3, 4, score=70.0)
    adj = baseline_resolver._build_tender_adjustment(pc, reason="consensus_match")
    assert adj["reason"] == "consensus_match"
    assert adj["baseline_source"] == "consensus"
    assert adj["adjusted_score"] == 0.0


# ============================================================ resolve_baseline L1 path


class _FakeSession:
    """空壳 AsyncSession,monkeypatch loaders 后 session 仅作 sentinel。"""


@pytest.mark.asyncio
async def test_resolve_baseline_l1_tender_full_match(monkeypatch):
    """L1 tender 命中:PC pair (a, b) shared hashes ⊆ tender → in excluded_pair_ids。"""
    pc = _pc(1, "text_similarity", 10, 20)

    async def _fake_tender_segs(session, pid):
        return {"h1", "h2", "h3"}

    async def _fake_bidder_pair(session, pid):
        return {10: {"h1", "h2"}, 20: {"h1", "h2"}}

    async def _fake_bidder_count(session, pid):
        return 4  # ≥3 bidders 但 tender 优先

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_segment_hashes", _fake_tender_segs
    )
    monkeypatch.setattr(
        baseline_resolver, "_load_bidder_pair_segment_hashes", _fake_bidder_pair
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _fake_bidder_count
    )

    res = await baseline_resolver.resolve_baseline(
        _FakeSession(), 1, "text_similarity", [pc]
    )
    assert res.excluded_pair_ids == {1}
    assert res.baseline_source == "tender"
    assert res.warnings == []


@pytest.mark.asyncio
async def test_resolve_baseline_l1_priority_over_low_bidder_count(monkeypatch):
    """L1 tender 优先于投标方数量门槛(2 bidders 也走 L1)。"""
    pc = _pc(1, "text_similarity", 10, 20)

    async def _fake_tender_segs(session, pid):
        return {"h1"}

    async def _fake_bidder_pair(session, pid):
        return {10: {"h1"}, 20: {"h1"}}

    async def _fake_bidder_count(session, pid):
        return 2  # ≤2 bidders 但有 tender → L1

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_segment_hashes", _fake_tender_segs
    )
    monkeypatch.setattr(
        baseline_resolver, "_load_bidder_pair_segment_hashes", _fake_bidder_pair
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _fake_bidder_count
    )

    res = await baseline_resolver.resolve_baseline(
        _FakeSession(), 1, "text_similarity", [pc]
    )
    assert res.excluded_pair_ids == {1}
    assert res.baseline_source == "tender"
    # L1 命中 → MUST NOT 出 L3 警示
    assert "baseline_unavailable_low_bidder_count" not in res.warnings


@pytest.mark.asyncio
async def test_resolve_baseline_l1_tender_no_match(monkeypatch):
    """tender 存在但 PC pair 共享段不在 tender → none(L1 路径活跃但无命中)。"""
    pc = _pc(1, "text_similarity", 10, 20)

    async def _fake_tender_segs(session, pid):
        return {"hX"}  # tender 有内容但与 PC 共享段不重合

    async def _fake_bidder_pair(session, pid):
        return {10: {"h1"}, 20: {"h1"}}  # shared = {h1},非 tender

    async def _fake_bidder_count(session, pid):
        return 4

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_segment_hashes", _fake_tender_segs
    )
    monkeypatch.setattr(
        baseline_resolver, "_load_bidder_pair_segment_hashes", _fake_bidder_pair
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _fake_bidder_count
    )

    res = await baseline_resolver.resolve_baseline(
        _FakeSession(), 1, "text_similarity", [pc]
    )
    assert res.excluded_pair_ids == set()
    assert res.baseline_source == "none"


@pytest.mark.asyncio
async def test_resolve_baseline_boq_dimension_uses_boq_loader(monkeypatch):
    """price_consistency / price_anomaly 维度走 BOQ loader 而非 segment loader。"""
    pc = _pc(1, "price_consistency", 10, 20)
    seg_called = {"v": False}
    boq_called = {"v": False}

    async def _seg_loader(session, pid):
        seg_called["v"] = True
        return set()

    async def _boq_loader(session, pid):
        boq_called["v"] = True
        return {"bh1"}

    async def _bidder_boq(session, pid):
        return {10: {"bh1"}, 20: {"bh1"}}

    async def _bidder_count(session, pid):
        return 4

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_segment_hashes", _seg_loader
    )
    monkeypatch.setattr(
        baseline_resolver, "_load_tender_boq_hashes", _boq_loader
    )
    monkeypatch.setattr(
        baseline_resolver, "_load_bidder_boq_hashes", _bidder_boq
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _bidder_count
    )

    res = await baseline_resolver.resolve_baseline(
        _FakeSession(), 1, "price_consistency", [pc]
    )
    assert seg_called["v"] is False
    assert boq_called["v"] is True
    assert res.excluded_pair_ids == {1}
    assert res.baseline_source == "tender"


@pytest.mark.asyncio
async def test_resolve_baseline_boq_no_consensus_fallback(monkeypatch):
    """BOQ 维度无 tender → 直接 none,不走 L2 共识(spec D5 决策)。"""
    pc = _pc(1, "price_consistency", 10, 20)

    async def _boq_loader(session, pid):
        return set()  # 无 tender BOQ

    async def _bidder_count(session, pid):
        return 5  # 即使 ≥3 bidders 也不走 consensus

    consensus_called = {"v": False}

    async def _segs_by_role(session, pid):
        consensus_called["v"] = True
        return {}

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_boq_hashes", _boq_loader
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _bidder_count
    )
    monkeypatch.setattr(
        baseline_resolver, "_load_bidder_segment_hashes_by_role", _segs_by_role
    )

    res = await baseline_resolver.resolve_baseline(
        _FakeSession(), 1, "price_consistency", [pc]
    )
    assert res.excluded_pair_ids == set()
    assert res.baseline_source == "none"
    assert res.warnings == []
    # 没有调 consensus loader(BOQ 不走 L2)
    assert consensus_called["v"] is False


# ============================================================ produce_baseline_adjustments


@pytest.mark.asyncio
async def test_produce_baseline_adjustments_returns_tender_match(monkeypatch):
    pc = _pc(1, "text_similarity", 10, 20, score=90.0)
    pc.is_ironclad = True

    async def _fake_tender_segs(session, pid):
        return {"h1"}

    async def _fake_bidder_pair(session, pid):
        return {10: {"h1"}, 20: {"h1"}}

    async def _bidder_count(session, pid):
        return 4

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_segment_hashes", _fake_tender_segs
    )
    monkeypatch.setattr(
        baseline_resolver, "_load_bidder_pair_segment_hashes", _fake_bidder_pair
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _bidder_count
    )

    adjs = await baseline_resolver.produce_baseline_adjustments(
        _FakeSession(), 1, "text_similarity", [pc]
    )
    assert len(adjs) == 1
    adj = adjs[0]
    assert adj["reason"] == "tender_match"
    assert adj["baseline_source"] == "tender"
    assert adj["adjusted_score"] == 0.0
    assert adj["raw_is_ironclad"] is True


@pytest.mark.asyncio
async def test_produce_baseline_adjustments_empty_when_no_match(monkeypatch):
    pc = _pc(1, "text_similarity", 10, 20)

    async def _fake_tender_segs(session, pid):
        return set()  # 无 tender

    async def _segs_by_role(session, pid):
        return {10: {"technical": {"h1"}}, 20: {"technical": {"h2"}}}  # 无共识

    async def _bidder_count(session, pid):
        return 5

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_segment_hashes", _fake_tender_segs
    )
    monkeypatch.setattr(
        baseline_resolver, "_load_bidder_segment_hashes_by_role", _segs_by_role
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _bidder_count
    )

    adjs = await baseline_resolver.produce_baseline_adjustments(
        _FakeSession(), 1, "text_similarity", [pc]
    )
    assert adjs == []
