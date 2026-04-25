"""L1 - _compute_dims_and_iron 扩 adjusted_pcs/adjusted_oas kwarg (CH-2)

替代原 compute_report 改造测试(round 3 H1 校正:compute_report 签名不动);
本测试覆盖 helper 级 kwarg 行为 + 6 步两次调用模拟 + C17 weights 透传。
"""

from __future__ import annotations

import inspect
from decimal import Decimal
from types import SimpleNamespace

from app.services.detect.judge import (
    _compute_dims_and_iron,
    _compute_formula_total,
    _compute_level,
    compute_report,
)


def _pc(pc_id: int, dim: str, score: float, iron: bool):
    return SimpleNamespace(
        id=pc_id,
        dimension=dim,
        score=Decimal(str(score)),
        is_ironclad=iron,
        bidder_a_id=1,
        bidder_b_id=2,
        evidence_json={},
    )


def _oa(oa_id: int, dim: str, score: float, has_iron: bool = False, source: str = "agent"):
    return SimpleNamespace(
        id=oa_id,
        dimension=dim,
        score=Decimal(str(score)),
        evidence_json={
            "source": source,
            "has_iron_evidence": has_iron,
        },
    )


# ============================================================ 签名契约不变(round 3 H1)


def test_compute_report_signature_unchanged():
    """compute_report 签名 2 参不变(主 spec L268 + L2843 既有契约)"""
    sig = inspect.signature(compute_report)
    params = list(sig.parameters.keys())
    assert params == ["pair_comparisons", "overall_analyses"]


def test_compute_dims_and_iron_default_none_behavior_unchanged():
    """_compute_dims_and_iron 默认 None 行为完全等价于本 change 前。"""
    pcs = [_pc(1, "structure_similarity", 100.0, True)]
    oas = []
    pdm, hi, dims = _compute_dims_and_iron(pcs, oas)
    assert pdm["structure_similarity"] == 100.0
    assert hi is True
    assert dims == ["structure_similarity"]


# ============================================================ adjusted dict 消费


def test_adjusted_pcs_score_overrides_raw():
    pcs = [_pc(1, "structure_similarity", 100.0, True)]
    oas = []
    apcs = {1: {"score": 0.0, "is_ironclad": False}}
    pdm, hi, dims = _compute_dims_and_iron(pcs, oas, adjusted_pcs=apcs)
    assert pdm["structure_similarity"] == 0.0
    assert hi is False
    assert dims == []


def test_adjusted_oas_score_overrides_raw():
    pcs = []
    oas = [_oa(1, "structure_similarity", 100.0, has_iron=True)]
    aoas = {1: {"score": 0.0, "has_iron_evidence": False}}
    pdm, hi, dims = _compute_dims_and_iron(pcs, oas, adjusted_oas=aoas)
    assert pdm["structure_similarity"] == 0.0
    assert hi is False


def test_adjusted_pc_partial_falls_back_to_raw():
    """adjusted_pcs[pc.id] 缺 score 字段 → 回落 ORM raw"""
    pcs = [_pc(1, "structure_similarity", 100.0, True)]
    apcs = {1: {"is_ironclad": False}}  # 只有 iron 没 score
    pdm, hi, _ = _compute_dims_and_iron(pcs, [], adjusted_pcs=apcs)
    assert pdm["structure_similarity"] == 100.0  # 回落 raw
    assert hi is False  # iron 已被抑制


# ============================================================ 6 步两次调用模拟


def test_two_pass_raw_then_adjusted_isolated():
    """同一组 fixture:第一次不传 kwarg → raw;第二次传 adjusted → adjusted 版本。

    验证 6 步顺序:第一次喂 DEF-OA 写入用 raw,第二次喂 final_total 用 adjusted。
    """
    pcs = [_pc(1, "structure_similarity", 100.0, True)]
    oas = [_oa(11, "structure_similarity", 100.0, has_iron=True, source="pair_aggregation")]
    # 第一次 raw
    raw_pdm, raw_hi, _ = _compute_dims_and_iron(pcs, oas)
    assert raw_pdm["structure_similarity"] == 100.0
    assert raw_hi is True
    # 第二次 adjusted(模拟 cluster 命中后 _apply_template_adjustments 产出)
    apcs = {1: {"score": 0.0, "is_ironclad": False}}
    aoas = {11: {"score": 0.0, "has_iron_evidence": False}}
    adj_pdm, adj_hi, _ = _compute_dims_and_iron(
        pcs, oas, adjusted_pcs=apcs, adjusted_oas=aoas
    )
    assert adj_pdm["structure_similarity"] == 0.0
    assert adj_hi is False


# ============================================================ C17 weights 透传(round 8 H2)


def test_compute_formula_total_with_custom_weights():
    """rules_config.weights 自定义权重透传 → final_total 反映 override"""
    pdm = {"structure_similarity": 100.0}
    # 默认权重 structure=0.08 → 100×0.08=8;自定义 0.30 → 100×0.30=30
    default_total = _compute_formula_total(pdm, has_ironclad=False)
    override_total = _compute_formula_total(
        pdm, has_ironclad=False, weights={"structure_similarity": 0.30}
    )
    assert override_total > default_total
    assert override_total == 30.0


def test_compute_level_with_custom_risk_levels():
    """rules_config.risk_levels 自定义阈值透传"""
    # 默认 70 high,40 medium
    assert _compute_level(75.0) == "high"
    # 自定义 80 high → 75 落 medium
    assert _compute_level(75.0, risk_levels={"high": 80, "medium": 40}) == "medium"


# ============================================================ 真围标 + 同模板


def test_real_collusion_with_template_iron_preserved():
    """text_sim iron=true 豁免保留 + section_similarity iron=true 保留 +
    error_consistency OA has_iron_evidence=true → has_ironclad=True → formula_total≥85"""
    pcs = [
        _pc(1, "text_similarity", 95.0, True),  # 模拟 LLM ≥3 段 plagiarism
        _pc(2, "section_similarity", 85.0, True),
    ]
    oas = [
        _oa(11, "error_consistency", 0, has_iron=True),
    ]
    # adjusted:text_sim 豁免保留(iron=true,score=raw);section/error_consistency 不受影响
    apcs = {1: {"score": 95.0, "is_ironclad": True}}
    aoas = {}
    pdm, hi, _ = _compute_dims_and_iron(
        pcs, oas, adjusted_pcs=apcs, adjusted_oas=aoas
    )
    assert hi is True  # has_ironclad
    total = _compute_formula_total(pdm, has_ironclad=True)
    assert total >= 85.0
