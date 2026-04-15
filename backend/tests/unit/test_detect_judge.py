"""L1 - detect/judge compute_report 单元测试 (C6 §9.4);C14 追加 clamp/ironclad helper"""

from __future__ import annotations

import inspect
from decimal import Decimal
from types import SimpleNamespace

from app.services.detect.judge import (
    DIMENSION_WEIGHTS,
    _clamp_with_llm,
    _compute_dims_and_iron,
    _compute_formula_total,
    _compute_level,
    compute_report,
)


def _pc(dimension: str, score: float, is_ironclad: bool = False):
    return SimpleNamespace(
        dimension=dimension,
        score=Decimal(str(score)),
        is_ironclad=is_ironclad,
        bidder_a_id=1,
        bidder_b_id=2,
        evidence_json={},
    )


def _oa(dimension: str, score: float, evidence_json: dict | None = None):
    return SimpleNamespace(
        dimension=dimension,
        score=Decimal(str(score)),
        evidence_json=evidence_json or {},
    )


def test_weights_sum_to_one():
    assert round(sum(DIMENSION_WEIGHTS.values()), 4) == 1.0


def test_empty_inputs_returns_zero_low():
    total, level = compute_report([], [])
    assert total == 0.0
    assert level == "low"


def test_all_dimensions_100_high():
    """C12 后 11 维度,权重和 = 1.00,全 100 → total = 100。"""
    pcs = [
        _pc("text_similarity", 100),
        _pc("section_similarity", 100),
        _pc("structure_similarity", 100),
        _pc("metadata_author", 100),
        _pc("metadata_time", 100),
        _pc("metadata_machine", 100),
        _pc("price_consistency", 100),
    ]
    oas = [
        _oa("error_consistency", 100),
        _oa("style", 100),
        _oa("image_reuse", 100),
        _oa("price_anomaly", 100),  # C12 新增 global 维度
    ]
    total, level = compute_report(pcs, oas)
    assert total == 100.0
    assert level == "high"


def test_partial_scores_medium():
    # 只给 2 个维度 50 分,其他 0(C12 后权重调整:price_consistency 0.10)
    pcs = [_pc("text_similarity", 50), _pc("price_consistency", 50)]
    total, level = compute_report(pcs, [])
    # 0.12 * 50 + 0.10 * 50 = 11.0 → low
    assert 0 < total < 15
    assert level == "low"


def test_ironclad_forces_min_85_high():
    # 铁证命中 → 强制 ≥ 85,等级 high
    pcs = [_pc("text_similarity", 10, is_ironclad=True)]
    total, level = compute_report(pcs, [])
    assert total >= 85.0
    assert level == "high"


def test_max_across_pairs():
    # 同维度 3 个 pair,取最高分
    pcs = [
        _pc("text_similarity", 30),
        _pc("text_similarity", 80),
        _pc("text_similarity", 50),
    ]
    total, _ = compute_report(pcs, [])
    # 0.12 * 80 = 9.6
    assert total == 9.6


def test_medium_threshold():
    # 凑 40-69 分(C12 后权重调整:price_consistency 0.10 + error_consistency 0.12
    # + text_similarity 0.12 + metadata_author 0.10 = 0.44 * 100 = 44)
    pcs = [_pc("price_consistency", 100)]  # 0.10 * 100 = 10
    oas = [_oa("error_consistency", 100)]  # 0.12 * 100 = 12
    pcs.append(_pc("text_similarity", 100))  # 0.12 * 100 = 12
    pcs.append(_pc("metadata_author", 100))  # 0.10 * 100 = 10
    # 合计 ~ 44 → medium
    total, level = compute_report(pcs, oas)
    assert 40 <= total < 70
    assert level == "medium"


# =========================================================== C14: clamp tests


def test_clamp_llm_upgrade_crosses_tier():
    """LLM 升分跨档 65 medium → 75 high"""
    final = _clamp_with_llm(65.0, 75.0, has_ironclad=False)
    assert final == 75.0
    assert _compute_level(final) == "high"


def test_clamp_llm_below_formula_no_effect():
    """LLM 建议 < formula → clamp 无效化,保留 formula"""
    final = _clamp_with_llm(80.0, 70.0, has_ironclad=False)
    assert final == 80.0


def test_clamp_ironclad_lower_bound_protects():
    """铁证下限守护:formula=88+铁证,LLM 建议 60 → final=88"""
    final = _clamp_with_llm(88.0, 60.0, has_ironclad=True)
    assert final == 88.0
    assert _compute_level(final) == "high"


def test_clamp_llm_with_ironclad_can_go_higher():
    """铁证 + LLM 升分:formula 先升到 85(铁证)+ LLM 建议 90 → final=90"""
    # 假设 formula_total 已被 compute_report 升到 85(铁证)
    final = _clamp_with_llm(85.0, 90.0, has_ironclad=True)
    assert final == 90.0


def test_clamp_ceiling_100():
    """天花板守护"""
    final = _clamp_with_llm(70.0, 150.0, has_ironclad=False)
    # 注:call_llm_judge 已拒绝超界 suggested,但 clamp 纯函数层面仍兜底
    assert final <= 100.0


# ============================================= C14: _compute_dims_and_iron helper


def test_detect_ironclad_pair_only():
    pcs = [_pc("text_similarity", 80, is_ironclad=True)]
    _per_dim, has_iron, dims = _compute_dims_and_iron(pcs, [])
    assert has_iron is True
    assert dims == ["text_similarity"]


def test_detect_ironclad_oa_only():
    oas = [_oa("error_consistency", 95, {"has_iron_evidence": True})]
    _per_dim, has_iron, dims = _compute_dims_and_iron([], oas)
    assert has_iron is True
    assert dims == ["error_consistency"]


def test_detect_ironclad_both_pair_and_oa():
    pcs = [_pc("text_similarity", 80, is_ironclad=True)]
    oas = [_oa("error_consistency", 95, {"has_iron_evidence": True})]
    _per_dim, has_iron, dims = _compute_dims_and_iron(pcs, oas)
    assert has_iron is True
    assert set(dims) == {"text_similarity", "error_consistency"}


def test_detect_ironclad_neither():
    pcs = [_pc("text_similarity", 80)]
    oas = [_oa("error_consistency", 50, {"has_iron_evidence": False})]
    _per_dim, has_iron, dims = _compute_dims_and_iron(pcs, oas)
    assert has_iron is False
    assert dims == []


def test_detect_ironclad_oa_evidence_non_dict():
    """OA.evidence_json 非 dict → 不触发铁证,不抛异常"""
    oas = [
        SimpleNamespace(
            dimension="style",
            score=Decimal("50"),
            evidence_json="not a dict",
        )
    ]
    _per_dim, has_iron, dims = _compute_dims_and_iron([], oas)
    assert has_iron is False


# ========================================= C14: compute_report signature contract


def test_compute_report_signature_unchanged():
    """compute_report 签名契约不变:2 参数 → (float, str) 返回"""
    sig = inspect.signature(compute_report)
    params = list(sig.parameters.keys())
    assert params == ["pair_comparisons", "overall_analyses"]
    # 返回类型 assertion:empty input 返 (0.0, 'low')
    total, level = compute_report([], [])
    assert isinstance(total, float)
    assert isinstance(level, str)


def test_dimension_weights_sum_and_keys_unchanged():
    """DIMENSION_WEIGHTS 11 维度 + 权重和 = 1.00"""
    assert round(sum(DIMENSION_WEIGHTS.values()), 4) == 1.0
    expected_keys = {
        "text_similarity",
        "section_similarity",
        "structure_similarity",
        "metadata_author",
        "metadata_time",
        "metadata_machine",
        "price_consistency",
        "price_anomaly",
        "error_consistency",
        "style",
        "image_reuse",
    }
    assert set(DIMENSION_WEIGHTS.keys()) == expected_keys


def test_compute_formula_total_pure_function():
    """内部 helper 纯函数契约"""
    per_dim = {"text_similarity": 100}
    # 0.12 * 100 = 12
    assert _compute_formula_total(per_dim, has_ironclad=False) == 12.0
    # 铁证升级
    assert _compute_formula_total(per_dim, has_ironclad=True) == 85.0
