"""模板簇识别 + adjustment 纯函数(CH-2 detect-template-exclusion)

招标方下发的同一 docx 模板被多家合规复用 → metadata/structure/style/text 多维度雪崩假阳。
本模块识别"模板簇"(同 author + doc_created_at)并对受污染维度做剔除/降权 + 铁证抑制,
不修改 ORM 实例(adjustments 不回写 DB,审计原始信号保留)。

设计要点(详见 openspec/changes/detect-template-exclusion/design.md):
- cluster_key = (nfkc_casefold_strip(author), doc_created_at_utc_truncated_to_second)
- 集合相交非空 + ≥2 bidder + 传递闭包 → 模板簇
- 剔除 4 维:structure_similarity / metadata_author / metadata_time / style(全覆盖)
- 降权 1 维:text_similarity ×0.5 + 铁证豁免(LLM plagiarism 判定)
- 不受影响 6 维:section_similarity / metadata_machine / price_consistency /
  price_anomaly / image_reuse / error_consistency
- 双 dict 隔离 PC/OA PK 命名空间;DEF-OA OA.id 必须同时被覆盖
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, TypedDict

from app.services.detect.agents.metadata_impl.normalizer import (
    nfkc_casefold_strip,
)

logger = logging.getLogger(__name__)


# ============================================================ Constants

# 与 parser/llm/role_classifier.py::VALID_ROLES 对齐
# 排除 qualification(PDF 噪音 author 常为通用值)+ other(无效分类)
TEMPLATE_FILE_ROLES: frozenset[str] = frozenset(
    {
        "technical",
        "construction",
        "bid_letter",
        "company_intro",
        "authorization",
        "pricing",
        "unit_price",
    }
)

# 受污染维度:剔除(score=0 + iron 抑制)
TEMPLATE_EXCLUSION_DIMENSIONS_PAIR: frozenset[str] = frozenset(
    {"structure_similarity", "metadata_author", "metadata_time"}
)

# 受污染维度:降权(score×0.5,铁证豁免)
TEMPLATE_DOWNGRADE_DIMENSIONS_PAIR: frozenset[str] = frozenset({"text_similarity"})

# 受污染维度:全覆盖才剔除的 global OA 维度
TEMPLATE_EXCLUSION_DIMENSIONS_GLOBAL: frozenset[str] = frozenset({"style"})

# text_similarity 降权因子(启发式,follow-up N-gram 精细化)
TEXT_SIM_DOWNGRADE_FACTOR: float = 0.5


# ============================================================ Types

AdjustedPCs = dict[int, dict]  # key = pc.id
AdjustedOAs = dict[int, dict]  # key = oa.id


class Adjustment(TypedDict, total=False):
    """JSONB 落地 shape;与 spec ADD Req "可观测性记录" 一致。

    scope="pc": pair 必填 / oa_id null / raw_is_ironclad bool / raw_has_iron_evidence null
    scope="global_oa" / "def_oa": pair null / oa_id 必填 / raw_is_ironclad null / raw_has_iron_evidence bool

    detect-tender-baseline §2 扩 reason:tender_match / consensus_match;
    baseline_source 字段(可选)只在 reason ∈ {tender_match, consensus_match} 时填。
    """

    scope: Literal["pc", "global_oa", "def_oa"]
    pair: list[int] | None
    oa_id: int | None
    dimension: str
    raw_score: float
    adjusted_score: float
    raw_is_ironclad: bool | None
    raw_has_iron_evidence: bool | None
    reason: Literal[
        "template_cluster_excluded",
        "template_cluster_downgraded",
        "template_cluster_excluded_all_members",
        "template_cluster_downgrade_suppressed_by_ironclad",
        "def_oa_aggregation_after_template_exclusion",
        "tender_match",
        "consensus_match",
    ]
    # detect-tender-baseline §2:tender_match/consensus_match 时填,
    # 其他 reason(metadata_cluster 路径)不填。
    baseline_source: Literal["tender", "consensus"]


# detect-tender-baseline §2:reason → priority(数值越大越强);
# 同 PC 多 adjustment 命中时仅保留 priority 最高的一条
# (spec ADD Req "baseline_resolver 与 template_cluster 协同契约":
# tender_match=3 > consensus_match=2 > template_cluster_*=1)
_REASON_PRIORITY: dict[str, int] = {
    "tender_match": 3,
    "consensus_match": 2,
    "template_cluster_excluded": 1,
    "template_cluster_downgraded": 1,
    "template_cluster_excluded_all_members": 1,
    "template_cluster_downgrade_suppressed_by_ironclad": 1,
    "def_oa_aggregation_after_template_exclusion": 1,
}


@dataclass
class TemplateCluster:
    """模板簇识别结果(等价类)。"""

    cluster_key_sample: dict
    bidder_ids: list[int] = field(default_factory=list)


# ============================================================ Helpers


def _normalize_created_at(dt: datetime | None) -> str | None:
    """归一化 doc_created_at:naive 视 UTC + astimezone(UTC) + 截秒 + ISO 字符串。

    防 aware/naive datetime 比较 TypeError + 漏匹配。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # naive 视 UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _build_cluster_key(
    author: str | None, created_at: datetime | None
) -> tuple[str, str] | None:
    """构造 cluster key (author_norm, created_at_norm);任一字段空 → 返 None 该文档跳过。

    author 用 nfkc_casefold_strip(与 metadata_author agent 语义对齐,防全角/大小写差异)。
    """
    author_norm = nfkc_casefold_strip(author)
    created_at_norm = _normalize_created_at(created_at)
    if author_norm is None or created_at_norm is None:
        return None
    return (author_norm, created_at_norm)


# ============================================================ Detection


def _detect_template_cluster(
    bidder_metadata_map: dict[int, list],
) -> list[TemplateCluster]:
    """识别模板簇:同 (author, created_at) 跨 ≥2 bidder 命中 → 同簇。

    Args:
        bidder_metadata_map: {bidder_id: [DocumentMetadata, ...]},调用方已按
            file_role in TEMPLATE_FILE_ROLES + Bidder.deleted_at IS NULL 过滤。

    Returns:
        TemplateCluster 列表(等价类,传递闭包合并)。空 list 时无簇命中。

    Failure: metadata 数据异常 → 上层捕获走原打分路径(本函数纯函数无 IO)。
    """
    # Step 1: 每个 bidder 构造 key 集合 S_i
    bidder_keys: dict[int, set[tuple[str, str]]] = {}
    for bidder_id, metas in bidder_metadata_map.items():
        keys: set[tuple[str, str]] = set()
        for meta in metas:
            key = _build_cluster_key(
                getattr(meta, "author", None),
                getattr(meta, "doc_created_at", None),
            )
            if key is None:
                logger.warning(
                    "template_cluster: bidder=%s doc=%s key incomplete",
                    bidder_id,
                    getattr(meta, "id", None),
                )
                continue
            keys.add(key)
        if not keys:
            logger.warning(
                "template_cluster: bidder=%s all keys incomplete", bidder_id
            )
        bidder_keys[bidder_id] = keys

    # Step 2: union-find 合并等价类(N≤20 规模 O(N²) 可接受)
    bidder_list = list(bidder_keys.keys())
    parent: dict[int, int] = {b: b for b in bidder_list}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    sample_key: dict[int, tuple[str, str]] = {}
    for i, bid_i in enumerate(bidder_list):
        for bid_j in bidder_list[i + 1 :]:
            inter = bidder_keys[bid_i] & bidder_keys[bid_j]
            if inter:
                union(bid_i, bid_j)
                # 任选一个共享 key 作 sample
                root = find(bid_i)
                if root not in sample_key:
                    sample_key[root] = next(iter(inter))

    # Step 3: 收集等价类(≥2 bidder 才成簇)
    groups: dict[int, list[int]] = {}
    for bid in bidder_list:
        if not bidder_keys[bid]:
            continue  # 无 key 的 bidder 不参与簇
        root = find(bid)
        groups.setdefault(root, []).append(bid)

    clusters: list[TemplateCluster] = []
    for root, members in groups.items():
        if len(members) < 2:
            continue
        key = sample_key.get(root)
        if key is None:
            # 同 root 但没记录 sample_key → 该根下任意 bidder 拿一个 key 作 sample
            for b in members:
                if bidder_keys[b]:
                    key = next(iter(bidder_keys[b]))
                    break
        if key is None:
            continue
        clusters.append(
            TemplateCluster(
                cluster_key_sample={"author": key[0], "created_at": key[1]},
                bidder_ids=sorted(members),
            )
        )
    return clusters


# ============================================================ Adjustment


def _is_pair_in_cluster(
    bidder_a: int, bidder_b: int, clusters: list[TemplateCluster]
) -> bool:
    """pair 两端 bidder 是否在**同一个**簇。"""
    for cluster in clusters:
        if bidder_a in cluster.bidder_ids and bidder_b in cluster.bidder_ids:
            return True
    return False


def _is_full_coverage(
    clusters: list[TemplateCluster], all_bidder_ids: set[int]
) -> bool:
    """style 全覆盖判定:len(clusters)==1 且 该簇 bidder_ids == 全部 bidder_ids。

    多簇并存或部分覆盖均返 False(本期简化,N-gram follow-up R5)。
    """
    if len(clusters) != 1:
        return False
    return set(clusters[0].bidder_ids) == all_bidder_ids


def _baseline_adjustment_to_pc_dict(adj: "Adjustment") -> dict:
    """Translate baseline (tender_match/consensus_match) Adjustment 为 adjusted_pcs[pc.id] 条目。

    spec ADD Req "baseline_resolver 与 template_cluster 协同契约" tender_match/consensus_match
    score 语义:score=0.0 + is_ironclad=False(从触发集剔除)+
    evidence_extras.template_cluster_excluded=True + baseline_source ∈ {tender, consensus}。
    """
    raw_score = adj.get("raw_score", 0.0)
    raw_iron = adj.get("raw_is_ironclad", False)
    return {
        "score": float(adj.get("adjusted_score", 0.0)),
        "is_ironclad": False,
        "evidence_extras": {
            "template_cluster_excluded": True,
            "baseline_source": adj.get("baseline_source", "none"),
            "raw_score": raw_score,
            "raw_is_ironclad": raw_iron,
        },
    }


def _apply_template_adjustments(
    pair_comparisons: list,
    overall_analyses: list,
    clusters: list[TemplateCluster],
    *,
    extra_adjustments: list[Adjustment] | None = None,
) -> tuple[AdjustedPCs, AdjustedOAs, list[Adjustment]]:
    """对受污染维度产 adjusted dict + adjustments 清单(不回写 DB)。

    Args:
        pair_comparisons: PC 行 list(SQLAlchemy ORM 实例,只读不改)
        overall_analyses: OA 行 list(全 11 行,DEF-OA 已 flush 拿到 PK)
        clusters: 模板簇识别结果
        extra_adjustments: detect-tender-baseline §2 加,baseline_resolver 喂入的
            tender_match/consensus_match Adjustment list。同 PC.id 多 source
            命中时,按 _REASON_PRIORITY 取最强 source(tender > consensus >
            metadata_cluster > none),低 priority 条目被丢弃。
            **向后兼容**:不传(或传 None/[])时行为完全等价于 detect-template-exclusion 归档时。

    Returns:
        (adjusted_pcs, adjusted_oas, adjustments):
            - adjusted_pcs: dict[pc.id, {score, is_ironclad, evidence_extras}]
            - adjusted_oas: dict[oa.id, {score, has_iron_evidence, evidence_extras}]
            - adjustments: 落 JSONB 的 entry 列表(scope=pc/global_oa/def_oa)
    """
    adjusted_pcs: AdjustedPCs = {}
    adjusted_oas: AdjustedOAs = {}
    adjustments: list[Adjustment] = []
    extras = list(extra_adjustments or [])

    # 无 cluster 也无 extra → 短路返空(老路径)
    if not clusters and not extras:
        return adjusted_pcs, adjusted_oas, adjustments

    # project 全部 bidder_ids:取 PC bidder + cluster bidder 并集
    # 用于 style 全覆盖判定:cluster.bidder_ids == project 全部 bidder
    all_bidder_ids: set[int] = set()
    for pc in pair_comparisons:
        if getattr(pc, "bidder_a_id", None) is not None:
            all_bidder_ids.add(pc.bidder_a_id)
        if getattr(pc, "bidder_b_id", None) is not None:
            all_bidder_ids.add(pc.bidder_b_id)
    for cluster in clusters:
        all_bidder_ids.update(cluster.bidder_ids)

    # ============================================================ PC entries

    for pc in pair_comparisons:
        dim = pc.dimension
        a = pc.bidder_a_id
        b = pc.bidder_b_id

        if not _is_pair_in_cluster(a, b, clusters):
            continue

        raw_score = float(pc.score) if pc.score is not None else 0.0
        raw_iron = bool(pc.is_ironclad)

        if dim in TEMPLATE_EXCLUSION_DIMENSIONS_PAIR:
            # 剔除:score=0 + iron 抑制
            adjusted_pcs[pc.id] = {
                "score": 0.0,
                "is_ironclad": False,
                "evidence_extras": {
                    "template_cluster_excluded": True,
                    "raw_score": raw_score,
                    "raw_is_ironclad": raw_iron,
                },
            }
            adjustments.append(
                {
                    "scope": "pc",
                    "pair": [a, b],
                    "oa_id": None,
                    "dimension": dim,
                    "raw_score": raw_score,
                    "adjusted_score": 0.0,
                    "raw_is_ironclad": raw_iron,
                    "raw_has_iron_evidence": None,
                    "reason": "template_cluster_excluded",
                }
            )
        elif dim in TEMPLATE_DOWNGRADE_DIMENSIONS_PAIR:
            # 降权 + 铁证豁免
            if raw_iron:
                # 铁证豁免:LLM 段级判定 ≥3 段 plagiarism → 模板外仍有真抄袭
                adjusted_pcs[pc.id] = {
                    "score": raw_score,  # 保留原分
                    "is_ironclad": True,  # iron 不抑制
                    "evidence_extras": {
                        "template_cluster_downgrade_suppressed_by_ironclad": True,
                        "raw_score": raw_score,
                    },
                }
                adjustments.append(
                    {
                        "scope": "pc",
                        "pair": [a, b],
                        "oa_id": None,
                        "dimension": dim,
                        "raw_score": raw_score,
                        "adjusted_score": raw_score,
                        "raw_is_ironclad": raw_iron,
                        "raw_has_iron_evidence": None,
                        "reason": (
                            "template_cluster_downgrade_suppressed_by_ironclad"
                        ),
                    }
                )
            else:
                adj = round(raw_score * TEXT_SIM_DOWNGRADE_FACTOR, 2)
                adjusted_pcs[pc.id] = {
                    "score": adj,
                    "is_ironclad": False,
                    "evidence_extras": {
                        "template_cluster_downgraded": True,
                        "raw_score": raw_score,
                    },
                }
                adjustments.append(
                    {
                        "scope": "pc",
                        "pair": [a, b],
                        "oa_id": None,
                        "dimension": dim,
                        "raw_score": raw_score,
                        "adjusted_score": adj,
                        "raw_is_ironclad": raw_iron,
                        "raw_has_iron_evidence": None,
                        "reason": "template_cluster_downgraded",
                    }
                )

    # ============================================================ Style global OA

    if _is_full_coverage(clusters, all_bidder_ids):
        for oa in overall_analyses:
            if oa.dimension not in TEMPLATE_EXCLUSION_DIMENSIONS_GLOBAL:
                continue
            raw_score = float(oa.score) if oa.score is not None else 0.0
            raw_has_iron = False
            if oa.evidence_json and isinstance(oa.evidence_json, dict):
                raw_has_iron = bool(
                    oa.evidence_json.get("has_iron_evidence", False)
                )
            adjusted_oas[oa.id] = {
                "score": 0.0,
                "has_iron_evidence": False,
                "evidence_extras": {
                    "template_cluster_excluded_all_members": True,
                    "raw_score": raw_score,
                },
            }
            adjustments.append(
                {
                    "scope": "global_oa",
                    "pair": None,
                    "oa_id": oa.id,
                    "dimension": oa.dimension,
                    "raw_score": raw_score,
                    "adjusted_score": 0.0,
                    "raw_is_ironclad": None,
                    "raw_has_iron_evidence": raw_has_iron,
                    "reason": "template_cluster_excluded_all_members",
                }
            )

    # ============================================================ Merge extras (baseline)

    # detect-tender-baseline §2:合并 baseline_resolver 喂入的 tender_match/consensus_match;
    # 同 PC.id 多 source 命中时按 _REASON_PRIORITY 取最强(tender > consensus > metadata_*)
    if extras:
        # 索引已存在的 PC-scope adjustments by (dimension, frozenset{a,b}) → list index
        pc_adj_index: dict[tuple[str, frozenset[int]], int] = {}
        for i, adj in enumerate(adjustments):
            if adj.get("scope") != "pc":
                continue
            pair_ids = adj.get("pair")
            if not pair_ids:
                continue
            key = (adj["dimension"], frozenset(pair_ids))
            pc_adj_index[key] = i

        # PC.id 查找:(dimension, frozenset{a,b}) → pc.id
        pc_id_lookup: dict[tuple[str, frozenset[int]], int] = {}
        for pc in pair_comparisons:
            a = getattr(pc, "bidder_a_id", None)
            b = getattr(pc, "bidder_b_id", None)
            if a is None or b is None:
                continue
            key = (pc.dimension, frozenset({a, b}))
            pc_id_lookup[key] = pc.id

        for extra in extras:
            if extra.get("scope") != "pc":
                continue  # baseline 仅产 pc-scope adjustments
            pair_ids = extra.get("pair")
            if not pair_ids:
                continue
            key = (extra["dimension"], frozenset(pair_ids))
            pc_id = pc_id_lookup.get(key)
            if pc_id is None:
                # extra 引用的 PC 不在 raw pair_comparisons 中(seed 漏)→ 静默跳过
                continue

            extra_priority = _REASON_PRIORITY.get(extra.get("reason", ""), 0)
            existing_idx = pc_adj_index.get(key)
            if existing_idx is not None:
                existing_priority = _REASON_PRIORITY.get(
                    adjustments[existing_idx].get("reason", ""), 0
                )
                if extra_priority <= existing_priority:
                    continue  # 保留现有(metadata_cluster) — 但 extras 优先级更高才覆盖
                # extra priority 更高 → 覆盖 metadata_cluster 自产条目
                adjustments[existing_idx] = extra
            else:
                adjustments.append(extra)
                pc_adj_index[key] = len(adjustments) - 1

            # apply to adjusted_pcs(覆盖式;baseline 优先于 metadata_cluster)
            adjusted_pcs[pc_id] = _baseline_adjustment_to_pc_dict(extra)

    # ============================================================ DEF-OA aggregation

    # 受污染维度的 DEF-OA OA 必须被 adjusted 覆盖(否则 helper 读 raw=100 → 抑制失效)
    affected_pair_dims = (
        TEMPLATE_EXCLUSION_DIMENSIONS_PAIR | TEMPLATE_DOWNGRADE_DIMENSIONS_PAIR
    )
    for oa in overall_analyses:
        if oa.dimension not in affected_pair_dims:
            continue
        # 判定是 DEF-OA(evidence_json.source == "pair_aggregation")
        is_def_oa = False
        if oa.evidence_json and isinstance(oa.evidence_json, dict):
            is_def_oa = oa.evidence_json.get("source") == "pair_aggregation"
        if not is_def_oa:
            continue

        # 该维度的全部 PC,score = max(adjusted-or-raw 全集)
        dim_pcs = [pc for pc in pair_comparisons if pc.dimension == oa.dimension]
        if not dim_pcs:
            continue

        def adj_score_of(pc) -> float:
            if pc.id in adjusted_pcs:
                return float(adjusted_pcs[pc.id]["score"])
            return float(pc.score) if pc.score is not None else 0.0

        def adj_iron_of(pc) -> bool:
            if pc.id in adjusted_pcs:
                return bool(adjusted_pcs[pc.id]["is_ironclad"])
            return bool(pc.is_ironclad)

        new_score = max((adj_score_of(pc) for pc in dim_pcs), default=0.0)
        new_iron = any(adj_iron_of(pc) for pc in dim_pcs)

        raw_score = float(oa.score) if oa.score is not None else 0.0
        raw_has_iron = False
        if oa.evidence_json and isinstance(oa.evidence_json, dict):
            raw_has_iron = bool(oa.evidence_json.get("has_iron_evidence", False))

        adjusted_oas[oa.id] = {
            "score": new_score,
            "has_iron_evidence": new_iron,
            "evidence_extras": {
                "raw_score": raw_score,
                "raw_has_iron_evidence": raw_has_iron,
            },
        }
        adjustments.append(
            {
                "scope": "def_oa",
                "pair": None,
                "oa_id": oa.id,
                "dimension": oa.dimension,
                "raw_score": raw_score,
                "adjusted_score": new_score,
                "raw_is_ironclad": None,
                "raw_has_iron_evidence": raw_has_iron,
                "reason": "def_oa_aggregation_after_template_exclusion",
            }
        )

    return adjusted_pcs, adjusted_oas, adjustments


__all__ = [
    "TemplateCluster",
    "Adjustment",
    "AdjustedPCs",
    "AdjustedOAs",
    "TEMPLATE_FILE_ROLES",
    "TEMPLATE_EXCLUSION_DIMENSIONS_PAIR",
    "TEMPLATE_DOWNGRADE_DIMENSIONS_PAIR",
    "TEMPLATE_EXCLUSION_DIMENSIONS_GLOBAL",
    "TEXT_SIM_DOWNGRADE_FACTOR",
    "_normalize_created_at",
    "_build_cluster_key",
    "_detect_template_cluster",
    "_apply_template_adjustments",
]
