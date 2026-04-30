"""L1 - baseline_resolver L2 共识 path 单测 (detect-tender-baseline §2)

覆盖 spec ADD Req "baseline_resolver 三级降级判定" L2 scenarios:
- 共识 ≥3 distinct bidders 命中
- 共识 ≤2 不达阈值 → 不剔除
- file_role 分组(同 hash 在 technical vs company_intro 分别计数)
- file_role ∈ {unknown, other} 不参与共识
- BOQ 维度 L2 不适用(test_baseline_resolver_l1.py 覆盖)

策略:_compute_consensus_hashes 是纯函数,无 DB 依赖,直接覆盖。
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.detect import baseline_resolver


# ============================================================ pure consensus


def test_consensus_hashes_three_bidders_hit_in_same_role():
    """h1 在 technical 标段命中 A/B/C 3 家 → 共识。"""
    bidder_hashes = {
        1: {"technical": {"h1"}},
        2: {"technical": {"h1"}},
        3: {"technical": {"h1"}},
    }
    consensus = baseline_resolver._compute_consensus_hashes(
        bidder_hashes, min_count=3
    )
    assert "h1" in consensus


def test_consensus_hashes_two_bidders_below_threshold():
    """h1 仅 2 家命中 → 不达阈值。"""
    bidder_hashes = {
        1: {"technical": {"h1"}},
        2: {"technical": {"h1"}},
    }
    consensus = baseline_resolver._compute_consensus_hashes(
        bidder_hashes, min_count=3
    )
    assert "h1" not in consensus


def test_consensus_hashes_file_role_grouping():
    """h1 在 technical 命中 A/B/C(共识),在 company_intro 仅 A/B(不共识)
    → 整体 h1 仍触发共识(任一分组达标即可)。"""
    bidder_hashes = {
        1: {"technical": {"h1"}, "company_intro": {"h1"}},
        2: {"technical": {"h1"}, "company_intro": {"h1"}},
        3: {"technical": {"h1"}},  # 仅 technical 有 h1
    }
    consensus = baseline_resolver._compute_consensus_hashes(
        bidder_hashes, min_count=3
    )
    # technical 分组 A/B/C 3 家命中 → 触发
    assert "h1" in consensus


def test_consensus_hashes_unknown_role_excluded():
    """file_role='unknown' 命中 ≥3 家 → MUST NOT 触发共识(spec scenario)。"""
    bidder_hashes = {
        1: {"unknown": {"h1"}},
        2: {"unknown": {"h1"}},
        3: {"unknown": {"h1"}},
    }
    consensus = baseline_resolver._compute_consensus_hashes(
        bidder_hashes, min_count=3
    )
    assert "h1" not in consensus


def test_consensus_hashes_other_role_excluded():
    """file_role='other' 同样不参与共识。"""
    bidder_hashes = {
        1: {"other": {"h1"}},
        2: {"other": {"h1"}},
        3: {"other": {"h1"}},
    }
    consensus = baseline_resolver._compute_consensus_hashes(
        bidder_hashes, min_count=3
    )
    assert "h1" not in consensus


def test_consensus_hashes_distinct_bidder_set_not_pair_count():
    """共识口径 = distinct bidder set 规模(D4),不是 PC pair 计数。"""
    # 同一 hash 出现在很多 PC pair 中,但只有 2 家 distinct bidder → 不触发
    bidder_hashes = {
        1: {"technical": {"h1"}},
        2: {"technical": {"h1"}},
        # 仅 2 家 distinct bidder
    }
    consensus = baseline_resolver._compute_consensus_hashes(
        bidder_hashes, min_count=3
    )
    assert "h1" not in consensus


def test_consensus_hashes_mixed_hashes():
    """h1 ∈ 共识、h2 不在共识 → 仅 h1 返。"""
    bidder_hashes = {
        1: {"technical": {"h1", "h2"}},
        2: {"technical": {"h1"}},
        3: {"technical": {"h1"}},
        4: {"technical": {"h2"}},  # h2 仅 1+4 二家
    }
    consensus = baseline_resolver._compute_consensus_hashes(
        bidder_hashes, min_count=3
    )
    assert "h1" in consensus
    assert "h2" not in consensus


def test_consensus_hashes_empty_bidder_hashes():
    consensus = baseline_resolver._compute_consensus_hashes({}, min_count=3)
    assert consensus == set()


# ============================================================ async resolve_baseline L2


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
async def test_resolve_baseline_l2_consensus_hit(monkeypatch):
    """无 tender + ≥3 bidders + 共识命中 → baseline_source='consensus'。"""
    pc = _pc(1, "text_similarity", 10, 20)

    async def _fake_tender_segs(session, pid):
        return set()  # 无 tender

    async def _fake_segs_by_role(session, pid):
        return {
            10: {"technical": {"h1"}},
            20: {"technical": {"h1"}},
            30: {"technical": {"h1"}},  # 第三家也命中 → 共识
        }

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
    assert res.excluded_pair_ids == {1}
    assert res.baseline_source == "consensus"


@pytest.mark.asyncio
async def test_resolve_baseline_l2_below_threshold_no_exclusion(monkeypatch):
    """无 tender + ≥3 bidders + 仅 2 家命中 → 不进 excluded_pair_ids。"""
    pc = _pc(1, "text_similarity", 10, 20)

    async def _fake_tender_segs(session, pid):
        return set()

    async def _fake_segs_by_role(session, pid):
        return {
            10: {"technical": {"h1"}},
            20: {"technical": {"h1"}},
            30: {"technical": {"h_other"}},  # 第三家无 h1 → 共识不达
        }

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
    assert res.excluded_pair_ids == set()
    assert res.baseline_source == "none"


@pytest.mark.asyncio
async def test_resolve_baseline_l2_unknown_role_no_consensus(monkeypatch):
    """无 tender + ≥3 bidders + 仅 unknown 标段命中 → 不触发共识。"""
    pc = _pc(1, "text_similarity", 10, 20)

    async def _fake_tender_segs(session, pid):
        return set()

    async def _fake_segs_by_role(session, pid):
        return {
            10: {"unknown": {"h1"}},
            20: {"unknown": {"h1"}},
            30: {"unknown": {"h1"}},
        }

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
    assert res.baseline_source == "none"
    assert res.excluded_pair_ids == set()
