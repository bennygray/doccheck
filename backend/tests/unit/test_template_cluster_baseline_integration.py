"""L1 - template_cluster._apply_template_adjustments + baseline 合并 (detect-tender-baseline §2.9)

覆盖 spec ADD Req "baseline_resolver 与 template_cluster 协同契约":
- 旧调用兼容(extra_adjustments 默认 [],行为完全等价于 detect-template-exclusion 归档时)
- tender_match adjustment 与 metadata_cluster adjustment 同 PC 取最强 source
- consensus_match adjustment 同样可单独喂入
- tender_match 覆盖 template_cluster_downgrade_suppressed_by_ironclad(铁证豁免覆盖)
- 不在 raw pair_comparisons 中的 extra(seed 漏)→ 静默跳过
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.detect.template_cluster import (
    Adjustment,
    TemplateCluster,
    _apply_template_adjustments,
)


def _pc(pc_id: int, dim: str, a_id: int, b_id: int, score: float, iron: bool = False):
    return SimpleNamespace(
        id=pc_id,
        dimension=dim,
        bidder_a_id=a_id,
        bidder_b_id=b_id,
        score=Decimal(str(score)),
        is_ironclad=iron,
        evidence_json={},
    )


def _oa(oa_id: int, dim: str, score: float = 0.0, source: str = "agent"):
    return SimpleNamespace(
        id=oa_id,
        dimension=dim,
        score=Decimal(str(score)),
        evidence_json={"source": source, "has_iron_evidence": False},
        manual_review_json=None,
    )


def _baseline_adj(
    *,
    pair: list[int],
    dim: str,
    raw_score: float,
    raw_iron: bool,
    reason: str,
) -> Adjustment:
    src = "tender" if reason == "tender_match" else "consensus"
    return {
        "scope": "pc",
        "pair": pair,
        "oa_id": None,
        "dimension": dim,
        "raw_score": raw_score,
        "adjusted_score": 0.0,
        "raw_is_ironclad": raw_iron,
        "raw_has_iron_evidence": None,
        "reason": reason,
        "baseline_source": src,
    }


# ============================================================ 老路径回归保护


def test_old_call_no_extras_metadata_cluster_only_unchanged():
    """不传 extra_adjustments 时,行为完全等价于 detect-template-exclusion 归档时。"""
    # 3 bidder 同模板,structure_similarity score=100 + iron=True
    pcs = [
        _pc(1, "structure_similarity", 1, 2, 100.0, iron=True),
        _pc(2, "structure_similarity", 1, 3, 100.0, iron=True),
        _pc(3, "structure_similarity", 2, 3, 100.0, iron=True),
    ]
    oas = []
    clusters = [
        TemplateCluster(
            cluster_key_sample={"author": "lp", "created_at": "2023-01-01"},
            bidder_ids=[1, 2, 3],
        )
    ]

    # 不传 extra_adjustments
    apcs, aoas, adjs = _apply_template_adjustments(pcs, oas, clusters)

    # 3 个 PC 均剔除 (template_cluster_excluded)
    assert len(apcs) == 3
    for pc_id in [1, 2, 3]:
        assert apcs[pc_id]["score"] == 0.0
        assert apcs[pc_id]["is_ironclad"] is False
    assert all(a["reason"] == "template_cluster_excluded" for a in adjs)


def test_old_call_explicit_none_extras_unchanged():
    """显式传 extra_adjustments=None 同样保留老行为。"""
    pcs = [_pc(1, "structure_similarity", 1, 2, 100.0, iron=True)]
    oas = []
    clusters = [
        TemplateCluster(
            cluster_key_sample={"author": "lp", "created_at": "2023-01-01"},
            bidder_ids=[1, 2],
        )
    ]
    apcs, aoas, adjs = _apply_template_adjustments(
        pcs, oas, clusters, extra_adjustments=None
    )
    assert apcs[1]["score"] == 0.0
    assert adjs[0]["reason"] == "template_cluster_excluded"


def test_old_call_explicit_empty_extras_unchanged():
    pcs = [_pc(1, "structure_similarity", 1, 2, 100.0, iron=True)]
    clusters = [
        TemplateCluster(
            cluster_key_sample={"author": "lp", "created_at": "2023-01-01"},
            bidder_ids=[1, 2],
        )
    ]
    apcs, _, adjs = _apply_template_adjustments(
        pcs, [], clusters, extra_adjustments=[]
    )
    assert adjs[0]["reason"] == "template_cluster_excluded"


# ============================================================ 新 reason 分支


def test_baseline_only_no_metadata_cluster():
    """无 metadata cluster + tender_match extras → 仅 tender_match adjustments。"""
    pcs = [
        _pc(1, "text_similarity", 1, 2, 88.0, iron=False),
        _pc(2, "text_similarity", 1, 3, 75.0, iron=False),
    ]
    extras = [
        _baseline_adj(
            pair=[1, 2],
            dim="text_similarity",
            raw_score=88.0,
            raw_iron=False,
            reason="tender_match",
        ),
    ]
    apcs, _, adjs = _apply_template_adjustments(
        pcs, [], clusters=[], extra_adjustments=extras
    )
    assert len(apcs) == 1
    assert apcs[1]["score"] == 0.0
    assert apcs[1]["is_ironclad"] is False
    assert apcs[1]["evidence_extras"]["baseline_source"] == "tender"
    assert apcs[1]["evidence_extras"]["template_cluster_excluded"] is True
    # PC 2 未被 tender_match 命中 → 不在 adjusted_pcs
    assert 2 not in apcs

    # adjustments 列表只含 1 条 tender_match
    assert len(adjs) == 1
    assert adjs[0]["reason"] == "tender_match"


def test_consensus_match_only():
    pcs = [_pc(1, "text_similarity", 1, 2, 90.0)]
    extras = [
        _baseline_adj(
            pair=[1, 2],
            dim="text_similarity",
            raw_score=90.0,
            raw_iron=False,
            reason="consensus_match",
        )
    ]
    apcs, _, adjs = _apply_template_adjustments(
        pcs, [], clusters=[], extra_adjustments=extras
    )
    assert apcs[1]["evidence_extras"]["baseline_source"] == "consensus"
    assert adjs[0]["reason"] == "consensus_match"


# ============================================================ 优先级合并


def test_tender_match_overrides_metadata_cluster_excluded():
    """同 PC.id 同时被 metadata cluster + tender_match 命中 → tender_match 胜
    (priority 3 > 1)。adjustments 仅保留 1 条 tender_match。"""
    pcs = [_pc(1, "structure_similarity", 1, 2, 100.0, iron=True)]
    clusters = [
        TemplateCluster(
            cluster_key_sample={"author": "lp", "created_at": "x"},
            bidder_ids=[1, 2],
        )
    ]
    extras = [
        _baseline_adj(
            pair=[1, 2],
            dim="structure_similarity",
            raw_score=100.0,
            raw_iron=True,
            reason="tender_match",
        )
    ]
    apcs, _, adjs = _apply_template_adjustments(
        pcs, [], clusters, extra_adjustments=extras
    )
    # 优先级:tender_match(3) > template_cluster_excluded(1)
    assert apcs[1]["evidence_extras"]["baseline_source"] == "tender"
    pc_adjs = [a for a in adjs if a["scope"] == "pc"]
    assert len(pc_adjs) == 1
    assert pc_adjs[0]["reason"] == "tender_match"


def test_tender_match_overrides_template_downgrade_suppressed_by_ironclad():
    """text_similarity raw_iron=True + metadata cluster → 老路径产
    template_cluster_downgrade_suppressed_by_ironclad(保留 iron=True);
    叠 tender_match → 必须覆盖 → is_ironclad=False(D14 设计本意)。"""
    pcs = [_pc(1, "text_similarity", 1, 2, 90.0, iron=True)]
    clusters = [
        TemplateCluster(
            cluster_key_sample={"author": "lp", "created_at": "x"},
            bidder_ids=[1, 2],
        )
    ]
    extras = [
        _baseline_adj(
            pair=[1, 2],
            dim="text_similarity",
            raw_score=90.0,
            raw_iron=True,
            reason="tender_match",
        )
    ]
    apcs, _, adjs = _apply_template_adjustments(
        pcs, [], clusters, extra_adjustments=extras
    )
    # tender_match 覆盖 → score=0, is_ironclad=False
    assert apcs[1]["score"] == 0.0
    assert apcs[1]["is_ironclad"] is False
    assert apcs[1]["evidence_extras"]["baseline_source"] == "tender"
    pc_adjs = [a for a in adjs if a["scope"] == "pc"]
    assert len(pc_adjs) == 1
    assert pc_adjs[0]["reason"] == "tender_match"


def test_consensus_match_overrides_metadata_cluster_excluded():
    """consensus_match priority=2 > template_cluster_excluded priority=1 → 覆盖。"""
    pcs = [_pc(1, "structure_similarity", 1, 2, 100.0, iron=True)]
    clusters = [
        TemplateCluster(
            cluster_key_sample={"author": "lp", "created_at": "x"},
            bidder_ids=[1, 2],
        )
    ]
    extras = [
        _baseline_adj(
            pair=[1, 2],
            dim="structure_similarity",
            raw_score=100.0,
            raw_iron=True,
            reason="consensus_match",
        )
    ]
    apcs, _, adjs = _apply_template_adjustments(
        pcs, [], clusters, extra_adjustments=extras
    )
    assert apcs[1]["evidence_extras"]["baseline_source"] == "consensus"
    pc_adjs = [a for a in adjs if a["scope"] == "pc"]
    assert len(pc_adjs) == 1
    assert pc_adjs[0]["reason"] == "consensus_match"


def test_extra_pair_not_in_pcs_silently_skipped():
    """extra 引用的 (dim, pair) 不在 pair_comparisons → 静默跳过(不报错,不入 adj)。"""
    pcs = [_pc(1, "text_similarity", 1, 2, 88.0)]
    extras = [
        _baseline_adj(
            pair=[99, 100],  # 不存在的 bidder pair
            dim="text_similarity",
            raw_score=80.0,
            raw_iron=False,
            reason="tender_match",
        )
    ]
    apcs, _, adjs = _apply_template_adjustments(
        pcs, [], clusters=[], extra_adjustments=extras
    )
    assert apcs == {}
    assert adjs == []


def test_lower_priority_extra_does_not_overwrite_higher_existing():
    """若 extras 内含 priority 更低的条目(例如 def_oa 类未来扩展),不能覆盖现有高优。
    本 case 用 metadata cluster 自产 + extras 内含同 dim/pair 的低 priority extra
    (这个不实际发生但保险测试)。"""
    pcs = [_pc(1, "structure_similarity", 1, 2, 100.0, iron=True)]
    clusters = [
        TemplateCluster(
            cluster_key_sample={"author": "lp", "created_at": "x"},
            bidder_ids=[1, 2],
        )
    ]
    # 注入一个 priority=1 的条目模拟"老调用方误传"——不应覆盖 metadata 产的条目
    weird_extra: Adjustment = {
        "scope": "pc",
        "pair": [1, 2],
        "oa_id": None,
        "dimension": "structure_similarity",
        "raw_score": 100.0,
        "adjusted_score": 0.0,
        "raw_is_ironclad": True,
        "raw_has_iron_evidence": None,
        "reason": "template_cluster_excluded",  # priority=1,与现有相等
    }
    apcs, _, adjs = _apply_template_adjustments(
        pcs, [], clusters, extra_adjustments=[weird_extra]
    )
    pc_adjs = [a for a in adjs if a["scope"] == "pc"]
    # priority 相等 → 保留先到的(metadata 自产条目),不重复
    assert len(pc_adjs) == 1
