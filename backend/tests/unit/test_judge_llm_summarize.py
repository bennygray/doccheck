"""L1 - judge_llm.summarize (C14)"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.detect.judge_llm import _shape_evidence_brief, summarize


def _pc(
    dim: str,
    score: float,
    bidder_a: int = 1,
    bidder_b: int = 2,
    is_ironclad: bool = False,
    evidence_json: dict | None = None,
):
    return SimpleNamespace(
        dimension=dim,
        score=Decimal(str(score)),
        bidder_a_id=bidder_a,
        bidder_b_id=bidder_b,
        is_ironclad=is_ironclad,
        evidence_json=evidence_json or {},
    )


def _oa(dim: str, score: float, evidence_json: dict | None = None):
    return SimpleNamespace(
        dimension=dim,
        score=Decimal(str(score)),
        evidence_json=evidence_json or {},
    )


def test_11_dims_all_present_even_if_empty():
    """哪怕没任何数据,11 维度全部出现在 summary.dimensions"""
    result = summarize(
        [],
        [],
        {},
        [],
        formula_total=0.0,
        formula_level="low",
        has_ironclad=False,
    )
    assert "dimensions" in result
    dims = result["dimensions"]
    assert len(dims) == 11
    for dim in [
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
    ]:
        assert dim in dims
        assert dims[dim]["max_score"] is None
        assert dims[dim]["top_k_examples"] == []


def test_top_k_descending_by_score():
    """top_k_examples 按 score 倒序"""
    pcs = [
        _pc("text_similarity", 30, bidder_a=1, bidder_b=2),
        _pc("text_similarity", 90, bidder_a=3, bidder_b=4),
        _pc("text_similarity", 60, bidder_a=5, bidder_b=6),
        _pc("text_similarity", 20, bidder_a=7, bidder_b=8),
    ]
    result = summarize(
        pcs,
        [],
        {"text_similarity": 90},
        [],
        formula_total=10.8,
        formula_level="low",
        has_ironclad=False,
        top_k=3,
    )
    examples = result["dimensions"]["text_similarity"]["top_k_examples"]
    assert len(examples) == 3
    scores = [e["score"] for e in examples]
    assert scores == sorted(scores, reverse=True)
    assert examples[0]["score"] == 90.0
    assert examples[1]["score"] == 60.0
    assert examples[2]["score"] == 30.0


def test_ironclad_always_included_even_if_not_top_k():
    """铁证 pair 无条件入 top_k_examples,即便排名在 k 之外"""
    pcs = [
        _pc("text_similarity", 90, bidder_a=1, bidder_b=2),
        _pc("text_similarity", 80, bidder_a=3, bidder_b=4),
        _pc("text_similarity", 70, bidder_a=5, bidder_b=6),
        _pc("text_similarity", 10, bidder_a=7, bidder_b=8, is_ironclad=True),
    ]
    result = summarize(
        pcs,
        [],
        {"text_similarity": 90},
        ["text_similarity"],
        formula_total=85.0,
        formula_level="high",
        has_ironclad=True,
        top_k=3,
    )
    examples = result["dimensions"]["text_similarity"]["top_k_examples"]
    # 前 3 高分 + 铁证(排第 4 位 10 分)共 4 条
    assert len(examples) == 4
    iron_ex = [e for e in examples if e["is_ironclad"]]
    assert len(iron_ex) == 1
    assert iron_ex[0]["score"] == 10.0
    assert result["dimensions"]["text_similarity"]["ironclad_count"] == 1


def test_skip_reason_from_oa_evidence():
    """global 型维度 enabled=false → skip_reason 透出"""
    oas = [
        _oa(
            "style",
            0,
            evidence_json={"enabled": False, "skip_reason": "<2 bidder"},
        )
    ]
    result = summarize(
        [],
        oas,
        {"style": 0},
        [],
        formula_total=0.0,
        formula_level="low",
        has_ironclad=False,
    )
    assert result["dimensions"]["style"]["skip_reason"] == "<2 bidder"
    assert result["dimensions"]["style"]["enabled"] is False


def test_pair_and_global_ironclad_both_counted():
    """pair 型(PC.is_ironclad)+ global 型(OA.evidence.has_iron_evidence)两种铁证都入摘要"""
    pcs = [_pc("text_similarity", 90, is_ironclad=True)]
    oas = [
        _oa(
            "error_consistency",
            95,
            evidence_json={"has_iron_evidence": True},
        )
    ]
    result = summarize(
        pcs,
        oas,
        {"text_similarity": 90, "error_consistency": 95},
        ["text_similarity", "error_consistency"],
        formula_total=85.0,
        formula_level="high",
        has_ironclad=True,
    )
    assert result["dimensions"]["text_similarity"]["ironclad_count"] == 1
    assert result["dimensions"]["error_consistency"]["ironclad_count"] == 1
    # global 型只有 1 条 OA 示例
    ec_ex = result["dimensions"]["error_consistency"]["top_k_examples"]
    assert len(ec_ex) == 1
    assert ec_ex[0]["bidder_a"] == "全局"
    assert ec_ex[0]["is_ironclad"] is True


def test_evidence_brief_extracts_preferred_keys():
    """_shape_evidence_brief 抽 preferred 字段"""
    ev = {
        "skip_reason": "disabled",
        "matched_keywords": ["a", "b", "c"],
        "llm_explanation": "something",
        "unused_noise_field": "x" * 500,
    }
    brief = _shape_evidence_brief(ev)
    assert "skip_reason=disabled" in brief
    assert "matched_keywords=a,b,c" in brief
    assert "llm_explanation=something" in brief
    assert "unused_noise_field" not in brief
    assert len(brief) <= 200


def test_evidence_brief_non_dict_returns_empty():
    assert _shape_evidence_brief(None) == ""
    assert _shape_evidence_brief("not a dict") == ""
    assert _shape_evidence_brief([1, 2, 3]) == ""


def test_formula_info_passed_through():
    result = summarize(
        [],
        [],
        {},
        ["error_consistency"],
        formula_total=85.0,
        formula_level="high",
        has_ironclad=True,
        project_info={"id": 42, "name": "测试项目", "bidder_count": 5},
    )
    assert result["project"] == {
        "id": 42,
        "name": "测试项目",
        "bidder_count": 5,
    }
    assert result["formula"]["total"] == 85.0
    assert result["formula"]["level"] == "high"
    assert result["formula"]["has_ironclad"] is True
    assert "error_consistency" in result["formula"]["ironclad_dimensions"]


def test_participating_bidders_deduped():
    pcs = [
        _pc("text_similarity", 80, bidder_a=1, bidder_b=2),
        _pc("text_similarity", 60, bidder_a=2, bidder_b=3),
        _pc("text_similarity", 40, bidder_a=1, bidder_b=3),
    ]
    result = summarize(
        pcs,
        [],
        {"text_similarity": 80},
        [],
        formula_total=9.6,
        formula_level="low",
        has_ironclad=False,
    )
    bidders = result["dimensions"]["text_similarity"]["participating_bidders"]
    assert set(bidders) == {1, 2, 3}
