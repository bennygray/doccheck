"""L1 - template_cluster._apply_template_adjustments 纯函数单测 (CH-2)

覆盖 spec ADD Req "模板簇维度剔除/降权与铁证抑制"。
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.detect.template_cluster import (
    TemplateCluster,
    _apply_template_adjustments,
)


def _pc(pc_id: int, dim: str, score: float, iron: bool, a: int, b: int):
    return SimpleNamespace(
        id=pc_id,
        dimension=dim,
        score=Decimal(str(score)),
        is_ironclad=iron,
        bidder_a_id=a,
        bidder_b_id=b,
        evidence_json={},
    )


def _oa(oa_id: int, dim: str, score: float, evidence_json: dict | None = None):
    return SimpleNamespace(
        id=oa_id,
        dimension=dim,
        score=Decimal(str(score)),
        evidence_json=evidence_json or {},
    )


def _def_oa(
    oa_id: int, dim: str, score: float, has_iron: bool = False
):
    return _oa(
        oa_id,
        dim,
        score,
        evidence_json={
            "source": "pair_aggregation",
            "best_score": score,
            "has_iron_evidence": has_iron,
            "pair_count": 3,
            "ironclad_pair_count": 3 if has_iron else 0,
        },
    )


def _cluster(bidder_ids):
    return TemplateCluster(
        cluster_key_sample={"author": "lp", "created_at": "2023-10-08T23:16:00+00:00"},
        bidder_ids=list(bidder_ids),
    )


# ============================================================ 剔除 4 维


def test_structure_pair_excluded_with_iron_suppression():
    """structure_similarity pair 两端同簇 + iron=true → score=0 + iron 抑制 + raw 写 evidence_extras"""
    pcs = [_pc(1, "structure_similarity", 100.0, True, 1, 2)]
    oas = [_def_oa(11, "structure_similarity", 100.0, has_iron=True)]
    clusters = [_cluster([1, 2, 3])]
    apcs, aoas, adjustments = _apply_template_adjustments(pcs, oas, clusters)
    assert apcs[1]["score"] == 0.0
    assert apcs[1]["is_ironclad"] is False
    assert apcs[1]["evidence_extras"]["raw_score"] == 100.0
    assert apcs[1]["evidence_extras"]["raw_is_ironclad"] is True
    # DEF-OA 同步覆盖
    assert 11 in aoas
    assert aoas[11]["score"] == 0.0
    assert aoas[11]["has_iron_evidence"] is False
    # adjustments scope 区分
    pc_entries = [a for a in adjustments if a["scope"] == "pc"]
    def_oa_entries = [a for a in adjustments if a["scope"] == "def_oa"]
    assert len(pc_entries) == 1
    assert pc_entries[0]["reason"] == "template_cluster_excluded"
    assert pc_entries[0]["raw_is_ironclad"] is True
    assert len(def_oa_entries) == 1
    assert def_oa_entries[0]["reason"] == "def_oa_aggregation_after_template_exclusion"


def test_structure_pair_one_in_one_out_not_adjusted():
    pcs = [_pc(1, "structure_similarity", 100.0, True, 1, 3)]  # 3 不在簇
    oas = []
    clusters = [_cluster([1, 2])]
    apcs, aoas, adjustments = _apply_template_adjustments(pcs, oas, clusters)
    assert apcs == {}
    assert adjustments == []


def test_metadata_author_iron_suppressed():
    pcs = [_pc(2, "metadata_author", 100.0, True, 1, 2)]
    oas = [_def_oa(12, "metadata_author", 100.0, has_iron=True)]
    apcs, aoas, _ = _apply_template_adjustments(pcs, oas, [_cluster([1, 2])])
    assert apcs[2]["is_ironclad"] is False
    assert aoas[12]["has_iron_evidence"] is False


def test_metadata_time_iron_suppressed():
    pcs = [_pc(3, "metadata_time", 100.0, True, 1, 2)]
    oas = [_def_oa(13, "metadata_time", 100.0, has_iron=True)]
    apcs, aoas, _ = _apply_template_adjustments(pcs, oas, [_cluster([1, 2])])
    assert apcs[3]["is_ironclad"] is False
    assert aoas[13]["has_iron_evidence"] is False


def test_style_full_coverage_excluded():
    pcs = []
    oas = [_oa(20, "style", 76.5)]
    clusters = [_cluster([1, 2, 3])]
    # 模拟 all_bidder_ids = {1, 2, 3} = cluster.bidder_ids → 全覆盖
    apcs, aoas, adjustments = _apply_template_adjustments(pcs, oas, clusters)
    assert aoas[20]["score"] == 0.0
    assert aoas[20]["has_iron_evidence"] is False
    # 注:style 不写 has_iron_evidence,evidence_extras 不断言 raw_has_iron_evidence
    global_oa_entries = [a for a in adjustments if a["scope"] == "global_oa"]
    assert len(global_oa_entries) == 1
    assert global_oa_entries[0]["dimension"] == "style"
    assert global_oa_entries[0]["reason"] == "template_cluster_excluded_all_members"


def test_style_partial_coverage_kept():
    """3 bidder 中 2 在簇 1 独立 → 部分覆盖,style 保留原分(round 7 M4)"""
    pcs = [
        # 加 1 个其他维度的 PC 让 all_bidder_ids 含 3
        _pc(99, "section_similarity", 50.0, False, 1, 3),
    ]
    oas = [_oa(20, "style", 76.5)]
    clusters = [_cluster([1, 2])]  # 簇仅含 1, 2;3 独立
    apcs, aoas, adjustments = _apply_template_adjustments(pcs, oas, clusters)
    # style 不调整(部分覆盖,先期简化)
    assert 20 not in aoas


# ============================================================ 降权 + 铁证豁免


def test_text_sim_downgrade_no_iron():
    pcs = [_pc(4, "text_similarity", 91.59, False, 1, 2)]
    oas = [_def_oa(14, "text_similarity", 91.59, has_iron=False)]
    apcs, aoas, adjustments = _apply_template_adjustments(
        pcs, oas, [_cluster([1, 2])]
    )
    assert apcs[4]["score"] == 45.80  # round(91.59 * 0.5, 2)
    assert apcs[4]["is_ironclad"] is False
    pc_entries = [a for a in adjustments if a["scope"] == "pc"]
    assert pc_entries[0]["reason"] == "template_cluster_downgraded"
    # DEF-OA score = max(adjusted PC scores) = 45.80
    assert aoas[14]["score"] == 45.80


def test_text_sim_iron_exempt():
    """text_sim PC iron=true → 不降权保留原分 + iron 保留 + reason=suppressed_by_ironclad"""
    pcs = [_pc(5, "text_similarity", 95.0, True, 1, 2)]
    oas = [_def_oa(15, "text_similarity", 95.0, has_iron=True)]
    apcs, aoas, adjustments = _apply_template_adjustments(
        pcs, oas, [_cluster([1, 2])]
    )
    assert apcs[5]["score"] == 95.0  # 不降权
    assert apcs[5]["is_ironclad"] is True
    pc_entries = [a for a in adjustments if a["scope"] == "pc"]
    assert pc_entries[0]["reason"] == "template_cluster_downgrade_suppressed_by_ironclad"
    # DEF-OA 同步保留高分 + iron(round 8 reviewer M4)
    assert aoas[15]["score"] == 95.0
    assert aoas[15]["has_iron_evidence"] is True


def test_text_sim_all_3_pcs_iron_full_exemption():
    """3 对 PC 全部 iron=true 全豁免 → DEF-OA score = max(raw) + has_iron_evidence=True

    round 8 reviewer M4 锁断言:防 fixture 写成"1 对豁免 2 对降权"漏 case。
    """
    pcs = [
        _pc(101, "text_similarity", 95.0, True, 1, 2),
        _pc(102, "text_similarity", 93.0, True, 1, 3),
        _pc(103, "text_similarity", 91.0, True, 2, 3),
    ]
    oas = [_def_oa(110, "text_similarity", 95.0, has_iron=True)]
    apcs, aoas, _ = _apply_template_adjustments(pcs, oas, [_cluster([1, 2, 3])])
    # 3 对 PC 全保留原分
    assert apcs[101]["score"] == 95.0
    assert apcs[102]["score"] == 93.0
    assert apcs[103]["score"] == 91.0
    # DEF-OA score = max(adjusted PC) = 95.0;has_iron_evidence = any iron = True
    assert aoas[110]["score"] == 95.0
    assert aoas[110]["has_iron_evidence"] is True


# ============================================================ 不受影响 6 维


def test_unaffected_dimensions_not_adjusted():
    """section_similarity / metadata_machine / price_consistency / price_anomaly /
    image_reuse / error_consistency 全部不调整(6 维)"""
    pcs = [
        _pc(50, "section_similarity", 70.0, False, 1, 2),
        _pc(51, "metadata_machine", 30.0, False, 1, 2),
        _pc(52, "price_consistency", 50.0, False, 1, 2),
    ]
    oas = [
        _oa(60, "price_anomaly", 20.0),
        _oa(61, "image_reuse", 88.0),
        _oa(62, "error_consistency", 40.0, evidence_json={"has_iron_evidence": False}),
    ]
    clusters = [_cluster([1, 2])]
    apcs, aoas, adjustments = _apply_template_adjustments(pcs, oas, clusters)
    assert apcs == {}
    assert aoas == {}
    assert adjustments == []


# ============================================================ 双 dict 命名空间隔离


def test_pc_id_vs_oa_id_namespace_isolation():
    """pc.id=1 和 oa.id=1 重叠时各自落 dict 不串(round 3 H3 锁)。"""
    pcs = [_pc(1, "structure_similarity", 100.0, True, 1, 2)]
    oas = [_def_oa(1, "structure_similarity", 100.0, has_iron=True)]  # 同 id=1
    apcs, aoas, _ = _apply_template_adjustments(pcs, oas, [_cluster([1, 2])])
    # 各自保留对应 entry,score 结构正确
    assert 1 in apcs
    assert apcs[1]["score"] == 0.0
    assert apcs[1]["is_ironclad"] is False
    assert 1 in aoas
    assert aoas[1]["score"] == 0.0
    assert aoas[1]["has_iron_evidence"] is False
    assert "is_ironclad" in apcs[1]
    assert "has_iron_evidence" in aoas[1]


def test_adjustment_does_not_mutate_orm():
    """adjustment 不改 ORM 实例 — pc.score / pc.is_ironclad 在函数前后保持原值。"""
    pc = _pc(1, "structure_similarity", 100.0, True, 1, 2)
    oa = _def_oa(11, "structure_similarity", 100.0, has_iron=True)
    pc_id_before = id(pc)
    pc_score_before = pc.score
    pc_iron_before = pc.is_ironclad
    oa_score_before = oa.score
    _apply_template_adjustments([pc], [oa], [_cluster([1, 2])])
    assert id(pc) == pc_id_before
    assert pc.score == pc_score_before
    assert pc.is_ironclad == pc_iron_before
    assert oa.score == oa_score_before


# ============================================================ 无 cluster 命中


def test_no_cluster_returns_empty_dicts():
    pcs = [_pc(1, "structure_similarity", 100.0, True, 1, 2)]
    oas = [_def_oa(11, "structure_similarity", 100.0, has_iron=True)]
    apcs, aoas, adjustments = _apply_template_adjustments(pcs, oas, [])
    assert apcs == {}
    assert aoas == {}
    assert adjustments == []
