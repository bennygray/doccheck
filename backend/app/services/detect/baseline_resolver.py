"""baseline_resolver: 三级降级判定 + Adjustment 生产者 (detect-tender-baseline §2)

设计要点(详见 openspec/changes/detect-tender-baseline/design.md D3/D14/D15):
- L1: project 关联 ≥1 份 extracted TenderDocument → tender hash 命中(L1 优先于投标方门槛)
- L2: 无 tender + bidder 数 ≥3 → 跨 bidder 共识(distinct set ≥3,按 file_role 分组,
      unknown/other 不计)
- L3: 无 tender + bidder 数 ≤2 → warnings='baseline_unavailable_low_bidder_count'
      不产 Adjustment,**不抑制 ironclad**(用户产品立场:基线缺失 ≠ 信号无效)
- BOQ 维度(price_consistency / price_anomaly)仅走 L1 tender 路径,L2 共识不适用
  (招标方下发同一份工程量清单给多家应标方是合法行为)

生产者-执行器分工 (D14):
- 本模块当**生产者**:产 reason ∈ {tender_match, consensus_match} 的 Adjustment list
- template_cluster._apply_template_adjustments 当**纯执行器**:合并 + 应用,
  不内嵌 baseline 业务分支

PC-level "fully baselined" 准则:
- shared_hashes := bidder_a 段 hash 集 ∩ bidder_b 段 hash 集(非 NULL,跨同 file_role)
- shared_hashes 非空 且 shared_hashes ⊆ baseline_hashes → 该 PC 进 excluded_pair_ids
- 部分命中(some shared but not all baseline) → 不进 excluded_pair_ids,
  由 §3 detector 段级处理(spec scenario "PC 内部分段命中 baseline 不豁免整 PC")
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_text import DocumentText
from app.models.price_item import PriceItem
from app.models.tender_document import TenderDocument

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.pair_comparison import PairComparison
    from app.services.detect.template_cluster import Adjustment

logger = logging.getLogger(__name__)


# ============================================================ Constants

# BOQ 维度仅走 L1 tender 路径(D5)
BOQ_DIMENSIONS: frozenset[str] = frozenset({"price_consistency", "price_anomaly"})

# L2 共识门槛(distinct bidder set 规模)
CONSENSUS_MIN_DISTINCT_BIDDERS: int = 3

# L3 警示门槛
LOW_BIDDER_THRESHOLD: int = 2

# 共识不参与的 file_role(分类噪音)
CONSENSUS_EXCLUDED_ROLES: frozenset[str] = frozenset({"unknown", "other"})

# L3 警示 code
WARN_LOW_BIDDER: str = "baseline_unavailable_low_bidder_count"


# ============================================================ Types


@dataclass
class BaselineResolution:
    """baseline_resolver.resolve_baseline 返回值。

    - excluded_pair_ids: PC.id 集合,这些 PC 整体被认定为 baseline 命中(score=0 + iron 抑制)
    - baseline_source: 整次调用产出的最强 source ∈ {tender, consensus, none}
    - warnings: L3 等场景的 warning code list
    """

    excluded_pair_ids: set[int] = field(default_factory=set)
    baseline_source: str = "none"
    warnings: list[str] = field(default_factory=list)


# ============================================================ Pure helpers


def _compute_consensus_hashes(
    bidder_role_hashes: dict[int, dict[str, set[str]]],
    *,
    min_count: int = CONSENSUS_MIN_DISTINCT_BIDDERS,
    excluded_roles: frozenset[str] = CONSENSUS_EXCLUDED_ROLES,
) -> set[str]:
    """跨 bidder 共识 hash 集合(L2)。

    Args:
        bidder_role_hashes: {bidder_id: {file_role: set[segment_hash]}}
        min_count: distinct bidder set 规模门槛(默认 3)
        excluded_roles: 不参与共识的 file_role(默认 {unknown, other})

    Returns:
        共识 hash 集合(任一 file_role 分组内 distinct bidder ≥ min_count)。

    口径:
    - distinct bidder set 规模(不是 PC pair 计数,见 design D4)
    - 按 file_role 分组(同 hash 在 technical vs company_intro 分别计数)
    - excluded_roles 内的段不参与共识计数
    """
    # role -> hash -> set[bidder_id]
    role_hash_bidders: dict[str, dict[str, set[int]]] = {}
    for bidder_id, role_map in bidder_role_hashes.items():
        for role, hashes in role_map.items():
            if not role or role in excluded_roles:
                continue
            for h in hashes:
                role_hash_bidders.setdefault(role, {}).setdefault(h, set()).add(
                    bidder_id
                )

    consensus: set[str] = set()
    for role, hash_map in role_hash_bidders.items():
        for h, bidders in hash_map.items():
            if len(bidders) >= min_count:
                consensus.add(h)
    return consensus


def _is_pc_fully_baselined(
    bidder_a_hashes: set[str],
    bidder_b_hashes: set[str],
    baseline_hashes: set[str],
) -> bool:
    """PC pair (a, b) 是否"完全 baseline 命中"。

    准则:shared_hashes := a ∩ b 非空 且 shared_hashes ⊆ baseline_hashes
    部分命中 (shared 含 non-baseline) → False,留给 §3 detector 段级处理
    无 shared → False(无可判定的 baseline 关联性)
    """
    if not baseline_hashes:
        return False
    shared = bidder_a_hashes & bidder_b_hashes
    if not shared:
        return False
    return shared.issubset(baseline_hashes)


def _build_tender_adjustment(
    pc: "PairComparison",
    *,
    reason: str,
) -> "Adjustment":
    """从 PC 构造 tender_match / consensus_match Adjustment 条目。

    score=0.0 + is_ironclad=False(spec ADD Req "baseline_resolver 与 template_cluster
    协同契约":tender_match/consensus_match score 语义)。
    """
    raw_score = float(pc.score) if pc.score is not None else 0.0
    raw_iron = bool(pc.is_ironclad)
    baseline_source = "tender" if reason == "tender_match" else "consensus"
    return {
        "scope": "pc",
        "pair": [pc.bidder_a_id, pc.bidder_b_id],
        "oa_id": None,
        "dimension": pc.dimension,
        "raw_score": raw_score,
        "adjusted_score": 0.0,
        "raw_is_ironclad": raw_iron,
        "raw_has_iron_evidence": None,
        "reason": reason,
        "baseline_source": baseline_source,
    }


# ============================================================ DB loaders


async def _load_tender_segment_hashes(
    session: "AsyncSession", project_id: int
) -> set[str]:
    """加载 project 下所有 extracted + 未软删 TenderDocument 的段级 hash 集合。"""
    stmt = select(TenderDocument.segment_hashes).where(
        TenderDocument.project_id == project_id,
        TenderDocument.parse_status == "extracted",
        TenderDocument.deleted_at.is_(None),
    )
    rows = (await session.execute(stmt)).scalars().all()
    out: set[str] = set()
    for h_list in rows:
        if h_list:
            out.update(h_list)
    return out


async def _load_tender_boq_hashes(
    session: "AsyncSession", project_id: int
) -> set[str]:
    """加载 project 下所有 extracted + 未软删 TenderDocument 的 BOQ 项级 hash 集合。"""
    stmt = select(TenderDocument.boq_baseline_hashes).where(
        TenderDocument.project_id == project_id,
        TenderDocument.parse_status == "extracted",
        TenderDocument.deleted_at.is_(None),
    )
    rows = (await session.execute(stmt)).scalars().all()
    out: set[str] = set()
    for h_list in rows:
        if h_list:
            out.update(h_list)
    return out


async def _load_bidder_segment_hashes_by_role(
    session: "AsyncSession", project_id: int
) -> dict[int, dict[str, set[str]]]:
    """加载 project 下每个 bidder 的段级 hash 集合,按 file_role 分组。

    Returns: {bidder_id: {file_role: set[segment_hash]}}
    - 仅含 segment_hash IS NOT NULL 的段(短段守门后非空)
    - 仅含未软删的 bidder
    - file_role NULL 归为 'unknown'
    """
    stmt = (
        select(Bidder.id, BidDocument.file_role, DocumentText.segment_hash)
        .join(BidDocument, BidDocument.bidder_id == Bidder.id)
        .join(DocumentText, DocumentText.bid_document_id == BidDocument.id)
        .where(
            Bidder.project_id == project_id,
            Bidder.deleted_at.is_(None),
            DocumentText.segment_hash.is_not(None),
        )
    )
    rows = (await session.execute(stmt)).all()
    out: dict[int, dict[str, set[str]]] = {}
    for bidder_id, role, h in rows:
        if h is None:
            continue
        out.setdefault(bidder_id, {}).setdefault(role or "unknown", set()).add(h)
    return out


async def _load_bidder_pair_segment_hashes(
    session: "AsyncSession", project_id: int
) -> dict[int, set[str]]:
    """加载 project 下每个 bidder 的段级 hash 全集(扁平,不按 role 分组)。

    供 PC pair 全匹配判定:跨 role 取并集即可,因为 PC pair 已锁定 dimension 维度。
    """
    stmt = (
        select(Bidder.id, DocumentText.segment_hash)
        .join(BidDocument, BidDocument.bidder_id == Bidder.id)
        .join(DocumentText, DocumentText.bid_document_id == BidDocument.id)
        .where(
            Bidder.project_id == project_id,
            Bidder.deleted_at.is_(None),
            DocumentText.segment_hash.is_not(None),
        )
    )
    rows = (await session.execute(stmt)).all()
    out: dict[int, set[str]] = {}
    for bidder_id, h in rows:
        if h is None:
            continue
        out.setdefault(bidder_id, set()).add(h)
    return out


async def _load_bidder_boq_hashes(
    session: "AsyncSession", project_id: int
) -> dict[int, set[str]]:
    """加载 project 下每个 bidder 的 BOQ 项级 hash 全集(D5/D7)。"""
    stmt = (
        select(PriceItem.bidder_id, PriceItem.boq_baseline_hash)
        .join(Bidder, Bidder.id == PriceItem.bidder_id)
        .where(
            Bidder.project_id == project_id,
            Bidder.deleted_at.is_(None),
            PriceItem.boq_baseline_hash.is_not(None),
        )
    )
    rows = (await session.execute(stmt)).all()
    out: dict[int, set[str]] = {}
    for bidder_id, h in rows:
        if h is None:
            continue
        out.setdefault(bidder_id, set()).add(h)
    return out


async def _count_alive_bidders(
    session: "AsyncSession", project_id: int
) -> int:
    """count of non-deleted bidders in project."""
    stmt = select(func.count(Bidder.id)).where(
        Bidder.project_id == project_id,
        Bidder.deleted_at.is_(None),
    )
    return int((await session.execute(stmt)).scalar_one())


# ============================================================ Public API


async def resolve_baseline(
    session: "AsyncSession",
    project_id: int,
    dimension: str,
    raw_pairs: Iterable["PairComparison"],
) -> BaselineResolution:
    """三级降级判定:L1 tender → L2 consensus → L3 警示。

    Args:
        session: AsyncSession
        project_id: 项目 id
        dimension: PC 维度名(text_similarity / section_similarity /
                   price_consistency / price_anomaly 等)
        raw_pairs: 该 dimension 下的 PC list(用于"完全 baseline"判定)

    Returns:
        BaselineResolution(excluded_pair_ids, baseline_source, warnings)

    BOQ 维度(price_consistency/price_anomaly)仅走 L1,跳过 L2/L3 共识。
    """
    is_boq = dimension in BOQ_DIMENSIONS
    raw_pairs_list = list(raw_pairs)

    # L1: tender path
    if is_boq:
        tender_hashes = await _load_tender_boq_hashes(session, project_id)
    else:
        tender_hashes = await _load_tender_segment_hashes(session, project_id)

    if tender_hashes:
        # tender 存在 → 走 L1 路径(L1 优先于投标方数量门槛,spec scenario)
        if is_boq:
            bidder_hashes_flat = await _load_bidder_boq_hashes(
                session, project_id
            )
        else:
            bidder_hashes_flat = await _load_bidder_pair_segment_hashes(
                session, project_id
            )

        excluded: set[int] = set()
        for pc in raw_pairs_list:
            a_hashes = bidder_hashes_flat.get(pc.bidder_a_id, set())
            b_hashes = bidder_hashes_flat.get(pc.bidder_b_id, set())
            if _is_pc_fully_baselined(a_hashes, b_hashes, tender_hashes):
                excluded.add(pc.id)
        return BaselineResolution(
            excluded_pair_ids=excluded,
            baseline_source="tender" if excluded else "none",
            warnings=[],
        )

    # 无 tender + BOQ → L2 不适用,直接 none
    if is_boq:
        return BaselineResolution(set(), "none", [])

    bidder_count = await _count_alive_bidders(session, project_id)

    # L3: ≤2 bidders + 无 tender → 警示但不抑制 ironclad
    if bidder_count <= LOW_BIDDER_THRESHOLD:
        return BaselineResolution(
            excluded_pair_ids=set(),
            baseline_source="none",
            warnings=[WARN_LOW_BIDDER],
        )

    # L2: ≥3 bidders + 无 tender → 共识
    bidder_role_hashes = await _load_bidder_segment_hashes_by_role(
        session, project_id
    )
    consensus_hashes = _compute_consensus_hashes(bidder_role_hashes)
    if not consensus_hashes:
        return BaselineResolution(set(), "none", [])

    # 用扁平(跨 role)hash 集做 PC 命中判定
    bidder_hashes_flat: dict[int, set[str]] = {}
    for bidder_id, role_map in bidder_role_hashes.items():
        agg: set[str] = set()
        for hashes in role_map.values():
            agg.update(hashes)
        bidder_hashes_flat[bidder_id] = agg

    excluded = set()
    for pc in raw_pairs_list:
        a_hashes = bidder_hashes_flat.get(pc.bidder_a_id, set())
        b_hashes = bidder_hashes_flat.get(pc.bidder_b_id, set())
        if _is_pc_fully_baselined(a_hashes, b_hashes, consensus_hashes):
            excluded.add(pc.id)

    return BaselineResolution(
        excluded_pair_ids=excluded,
        baseline_source="consensus" if excluded else "none",
        warnings=[],
    )


async def produce_baseline_adjustments(
    session: "AsyncSession",
    project_id: int,
    dimension: str,
    raw_pairs: Iterable["PairComparison"],
) -> list["Adjustment"]:
    """生产者:对该 dimension 的 raw_pairs 产 tender_match/consensus_match Adjustment list。

    每个 PC 至多产一条 Adjustment(同 PC 多 source 命中由 resolve_baseline 内部以
    L1>L2 优先级决定,本函数只看 baseline_source 决定 reason)。

    Returns:
        Adjustment list(scope='pc',reason ∈ {tender_match, consensus_match})。
        无命中时返空 list。
    """
    raw_pairs_list = list(raw_pairs)
    resolution = await resolve_baseline(
        session, project_id, dimension, raw_pairs_list
    )
    if not resolution.excluded_pair_ids:
        return []

    reason = (
        "tender_match"
        if resolution.baseline_source == "tender"
        else "consensus_match"
    )
    pc_by_id = {pc.id: pc for pc in raw_pairs_list}
    adjustments: list[Adjustment] = []
    for pc_id in resolution.excluded_pair_ids:
        pc = pc_by_id.get(pc_id)
        if pc is None:
            continue
        adjustments.append(_build_tender_adjustment(pc, reason=reason))
    return adjustments


@dataclass
class SegmentBaselineHashes:
    """detector 段级用:hash → source 映射 + 整体最强 source + warnings。

    与 BaselineResolution 区别:不基于 raw_pairs 做 PC 全匹配判定,
    返回 ALL baseline hashes 让 detector 段级判 baseline_matched。
    """

    hash_to_source: dict[str, str] = field(default_factory=dict)
    # 整体最强 source(取所有命中段 source 中的最强,priority tender>consensus>none)
    baseline_source: str = "none"
    warnings: list[str] = field(default_factory=list)


_SOURCE_PRIORITY: dict[str, int] = {"tender": 3, "consensus": 2, "none": 0}


async def get_excluded_segment_hashes_with_source(
    session: "AsyncSession",
    project_id: int,
    dimension: str,
) -> SegmentBaselineHashes:
    """detector 段级 API:返回该 dimension 下的 baseline hash → source 映射。

    detector 段级 ironclad 跳过 + evidence_json.samples[i] baseline_matched 用此映射;
    PC-level wholesale 兜底由 produce_baseline_adjustments 单独负责(judge step5)。

    三级降级与 resolve_baseline 一致:
    - L1 tender: project 有 ≥1 份 extracted TenderDocument → 返 tender_hashes
    - L2 consensus: 无 tender + ≥3 bidders → 返共识 hash 集合
    - L3 ≤2 bidders + 无 tender: 返空 hash + warnings='baseline_unavailable_low_bidder_count'

    BOQ 维度仅走 L1(D5);非 BOQ 维度全套三级降级。
    """
    is_boq = dimension in BOQ_DIMENSIONS

    if is_boq:
        tender_hashes = await _load_tender_boq_hashes(session, project_id)
    else:
        tender_hashes = await _load_tender_segment_hashes(session, project_id)

    if tender_hashes:
        # L1: tender 路径活跃(L1 优先于投标方数量门槛)
        return SegmentBaselineHashes(
            hash_to_source={h: "tender" for h in tender_hashes},
            baseline_source="tender",
            warnings=[],
        )

    # 无 tender + BOQ → none(BOQ 不走 L2/L3 共识)
    if is_boq:
        return SegmentBaselineHashes(
            hash_to_source={},
            baseline_source="none",
            warnings=[],
        )

    bidder_count = await _count_alive_bidders(session, project_id)

    # L3: ≤2 bidders + 无 tender → 警示
    if bidder_count <= LOW_BIDDER_THRESHOLD:
        return SegmentBaselineHashes(
            hash_to_source={},
            baseline_source="none",
            warnings=[WARN_LOW_BIDDER],
        )

    # L2: ≥3 bidders + 无 tender → 共识
    bidder_role_hashes = await _load_bidder_segment_hashes_by_role(
        session, project_id
    )
    consensus_hashes = _compute_consensus_hashes(bidder_role_hashes)
    if not consensus_hashes:
        return SegmentBaselineHashes(
            hash_to_source={},
            baseline_source="none",
            warnings=[],
        )
    return SegmentBaselineHashes(
        hash_to_source={h: "consensus" for h in consensus_hashes},
        baseline_source="consensus",
        warnings=[],
    )


async def get_excluded_price_item_ids(
    session: "AsyncSession",
    project_id: int,
) -> set[int]:
    """detect-tender-baseline §6 (D15):返 project 下命中 tender BOQ baseline 的
    PriceItem.id 集合。

    SQL 拼装归属本模块(spec ADD Req "SQL 拼装归属契约":detector 不直拼 baseline SQL,
    避免 baseline 业务泄漏到 detector 层)。`price_anomaly.run()` 拿到此集合后透传给
    `aggregate_bidder_totals(excluded_price_item_ids=...)`(D15)。

    BOQ-only:此函数仅适用于 BOQ 维度(price_anomaly / price_consistency 等);
    section/text 维度走 segment_hash 集合,不走此 SQL。

    无 tender / 空 boq_baseline_hashes / 该 project 下无命中行 → 返空 set(短路安全)。
    """
    tender_hashes = await _load_tender_boq_hashes(session, project_id)
    if not tender_hashes:
        return set()
    stmt = (
        select(PriceItem.id)
        .join(Bidder, Bidder.id == PriceItem.bidder_id)
        .where(
            Bidder.project_id == project_id,
            Bidder.deleted_at.is_(None),
            PriceItem.boq_baseline_hash.is_not(None),
            PriceItem.boq_baseline_hash.in_(tender_hashes),
        )
    )
    return set((await session.execute(stmt)).scalars().all())


__all__ = [
    "BaselineResolution",
    "SegmentBaselineHashes",
    "BOQ_DIMENSIONS",
    "CONSENSUS_MIN_DISTINCT_BIDDERS",
    "LOW_BIDDER_THRESHOLD",
    "CONSENSUS_EXCLUDED_ROLES",
    "WARN_LOW_BIDDER",
    "_compute_consensus_hashes",
    "_is_pc_fully_baselined",
    "_build_tender_adjustment",
    "resolve_baseline",
    "produce_baseline_adjustments",
    "get_excluded_segment_hashes_with_source",
    "get_excluded_price_item_ids",
]
