"""L1 - detect/judge compute_report 单元测试 (C6 §9.4)"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.detect.judge import DIMENSION_WEIGHTS, compute_report


def _pc(dimension: str, score: float, is_ironclad: bool = False):
    return SimpleNamespace(
        dimension=dimension,
        score=Decimal(str(score)),
        is_ironclad=is_ironclad,
    )


def _oa(dimension: str, score: float):
    return SimpleNamespace(dimension=dimension, score=Decimal(str(score)))


def test_weights_sum_to_one():
    assert round(sum(DIMENSION_WEIGHTS.values()), 4) == 1.0


def test_empty_inputs_returns_zero_low():
    total, level = compute_report([], [])
    assert total == 0.0
    assert level == "low"


def test_all_dimensions_100_high():
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
    ]
    total, level = compute_report(pcs, oas)
    assert total == 100.0
    assert level == "high"


def test_partial_scores_medium():
    # 只给 2 个维度 50 分,其他 0
    pcs = [_pc("text_similarity", 50), _pc("price_consistency", 50)]
    total, level = compute_report(pcs, [])
    # 0.12 * 50 + 0.15 * 50 = 13.5 → low
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
    # 凑 40-69 分
    pcs = [_pc("price_consistency", 100)]  # 0.15 * 100 = 15
    oas = [_oa("error_consistency", 100)]  # 0.12 * 100 = 12
    pcs.append(_pc("text_similarity", 100))  # 0.12 * 100 = 12
    pcs.append(_pc("metadata_author", 100))  # 0.10 * 100 = 10
    # 合计 ~ 49 → medium
    total, level = compute_report(pcs, oas)
    assert 40 <= total < 70
    assert level == "medium"
