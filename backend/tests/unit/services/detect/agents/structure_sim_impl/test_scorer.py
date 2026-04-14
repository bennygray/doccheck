"""L1 - C9 scorer(三维度聚合 + evidence_json)"""

from __future__ import annotations

from app.services.detect.agents.structure_sim_impl import scorer
from app.services.detect.agents.structure_sim_impl.models import (
    DirResult,
    FieldSimResult,
    FillSimResult,
    SheetFieldResult,
    SheetFillResult,
)

_W = (0.4, 0.3, 0.3)


def _dir(score: float) -> DirResult:
    return DirResult(
        score=score,
        titles_a_count=10,
        titles_b_count=10,
        lcs_length=int(score * 10),
        sample_titles_matched=[],
    )


def _field(score: float) -> FieldSimResult:
    return FieldSimResult(
        score=score,
        per_sheet=[
            SheetFieldResult(
                sheet_name="S",
                header_sim=score,
                bitmask_sim=score,
                merged_cells_sim=score,
                sub_score=score,
            )
        ],
    )


def _fill(score: float) -> FillSimResult:
    return FillSimResult(
        score=score,
        per_sheet=[
            SheetFillResult(
                sheet_name="S",
                score=score,
                matched_pattern_lines=5,
                sample_patterns=[],
            )
        ],
    )


def test_aggregate_all_three_participate():
    r = scorer.aggregate_structure_score(_dir(1.0), _field(0.5), _fill(0.5), _W)
    # 1.0*0.4 + 0.5*0.3 + 0.5*0.3 = 0.70
    assert r.score == 70.0
    assert set(r.participating_dimensions) == {"directory", "field_structure", "fill_pattern"}
    assert r.weights_used == {"directory": 0.4, "field_structure": 0.3, "fill_pattern": 0.3}


def test_aggregate_only_two_dimensions_renormalized():
    """仅目录+填充参与 → 按 0.4/0.7 + 0.3/0.7 归一化。"""
    r = scorer.aggregate_structure_score(_dir(1.0), None, _fill(0.5), _W)
    # (1.0*0.4 + 0.5*0.3) / 0.7 = 0.55/0.7 ≈ 0.7857
    assert abs(r.score - 78.57) < 0.02
    assert r.participating_dimensions == ["directory", "fill_pattern"]
    assert "field_structure" not in r.weights_used


def test_aggregate_only_one_dimension_equivalent_to_self():
    """仅一个维度参与 → score = 该维度 × 100(重归一化后权重 1.0)。"""
    r = scorer.aggregate_structure_score(None, _field(0.8), None, _W)
    assert r.score == 80.0
    assert r.participating_dimensions == ["field_structure"]


def test_aggregate_all_none_returns_none():
    r = scorer.aggregate_structure_score(None, None, None, _W)
    assert r.score is None
    assert r.participating_dimensions == []
    assert r.weights_used == {}
    assert r.is_ironclad is False


def test_aggregate_is_ironclad_all_conditions_met():
    """任一维度 ≥ 0.9 且 total ≥ 85 → is_ironclad True。"""
    r = scorer.aggregate_structure_score(_dir(0.95), _field(0.9), _fill(0.8), _W)
    # 0.95*0.4 + 0.9*0.3 + 0.8*0.3 = 0.38+0.27+0.24 = 0.89 → 89%
    assert r.score == 89.0
    assert r.is_ironclad is True


def test_aggregate_is_ironclad_sub_threshold_not_met():
    """即使 total ≥ 85,但无维度 ≥ 0.9 → is_ironclad False。"""
    r = scorer.aggregate_structure_score(_dir(0.89), _field(0.89), _fill(0.89), _W)
    # 0.89 * 1.0 = 0.89 → 89% ≥ 85 但 max_sub=0.89 < 0.9 → False
    assert r.score == 89.0
    assert r.is_ironclad is False


def test_aggregate_is_ironclad_total_threshold_not_met():
    """有维度 ≥ 0.9 但 total < 85 → False。"""
    r = scorer.aggregate_structure_score(_dir(0.95), _field(0.5), _fill(0.5), _W)
    # 0.95*0.4 + 0.5*0.3 + 0.5*0.3 = 0.68 → 68
    assert r.score == 68.0
    assert r.is_ironclad is False


def test_aggregate_custom_weights():
    """自定权重:(0.6, 0.2, 0.2)。"""
    r = scorer.aggregate_structure_score(
        _dir(1.0), _field(0.0), _fill(0.0), (0.6, 0.2, 0.2)
    )
    # 1.0*0.6 + 0 + 0 = 0.6 → 60
    assert r.score == 60.0


def test_build_evidence_json_three_dims():
    dir_r = _dir(0.9)
    field_r = _field(0.8)
    fill_r = _fill(0.7)
    agg = scorer.aggregate_structure_score(dir_r, field_r, fill_r, _W)
    ev = scorer.build_evidence_json(
        dir_r,
        field_r,
        fill_r,
        agg,
        doc_role="bid_letter",
        doc_id_a=[1, 2],
        doc_id_b=[3, 4],
    )
    assert ev["algorithm"] == "structure_sim_v1"
    assert ev["doc_role"] == "bid_letter"
    assert ev["doc_id_a"] == [1, 2]
    assert ev["doc_id_b"] == [3, 4]
    assert set(ev["participating_dimensions"]) == {"directory", "field_structure", "fill_pattern"}
    assert ev["dimensions"]["directory"]["score"] == 0.9
    assert ev["dimensions"]["directory"]["reason"] is None
    assert ev["dimensions"]["field_structure"]["per_sheet"][0]["sheet_name"] == "S"
    assert ev["dimensions"]["fill_pattern"]["score"] == 0.7


def test_build_evidence_json_with_skip_reasons():
    agg = scorer.aggregate_structure_score(_dir(0.8), None, None, _W)
    ev = scorer.build_evidence_json(
        _dir(0.8),
        None,
        None,
        agg,
        doc_role="tech_scheme",
        field_skip_reason="xlsx_sheet_missing",
        fill_skip_reason="xlsx_sheet_missing",
    )
    assert ev["dimensions"]["directory"]["score"] == 0.8
    assert ev["dimensions"]["field_structure"]["score"] is None
    assert ev["dimensions"]["field_structure"]["reason"] == "xlsx_sheet_missing"
    assert ev["dimensions"]["field_structure"]["per_sheet"] == []
    assert ev["dimensions"]["fill_pattern"]["score"] is None


def test_build_evidence_json_agent_skip():
    """Agent 级 skip:3 维度全 None。"""
    agg = scorer.aggregate_structure_score(None, None, None, _W)
    ev = scorer.build_evidence_json(
        None, None, None, agg, doc_role="unknown"
    )
    assert agg.score is None
    assert ev["participating_dimensions"] == []
    assert ev["dimensions"]["directory"]["score"] is None
    assert ev["dimensions"]["field_structure"]["score"] is None
    assert ev["dimensions"]["fill_pattern"]["score"] is None
