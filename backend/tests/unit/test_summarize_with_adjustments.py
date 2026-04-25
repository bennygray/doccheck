"""L1 - summarize / _is_pc_ironclad / _is_oa_ironclad 扩 adjusted dict (CH-2 round 3 H1)

防 LLM 拿污染 raw 值输出高 suggested_total → clamp 拉回污染分。
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.detect.judge_llm import (
    _is_oa_ironclad,
    _is_pc_ironclad,
    summarize,
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


def _oa(oa_id: int, dim: str, score: float, has_iron: bool = False):
    return SimpleNamespace(
        id=oa_id,
        dimension=dim,
        score=Decimal(str(score)),
        evidence_json={
            "source": "pair_aggregation",
            "has_iron_evidence": has_iron,
        },
    )


def test_is_pc_ironclad_default_none_reads_raw():
    pc = _pc(1, "structure_similarity", 100.0, True)
    assert _is_pc_ironclad(pc) is True
    pc2 = _pc(2, "structure_similarity", 100.0, False)
    assert _is_pc_ironclad(pc2) is False


def test_is_pc_ironclad_with_adjusted_overrides_raw():
    pc = _pc(1, "structure_similarity", 100.0, True)
    apcs = {1: {"is_ironclad": False, "score": 0.0}}
    assert _is_pc_ironclad(pc, adjusted_pcs=apcs) is False


def test_is_oa_ironclad_default_none_reads_raw():
    oa = _oa(1, "error_consistency", 50.0, has_iron=True)
    assert _is_oa_ironclad(oa) is True


def test_is_oa_ironclad_with_adjusted_overrides_raw():
    oa = _oa(1, "metadata_author", 100.0, has_iron=True)
    aoas = {1: {"has_iron_evidence": False, "score": 0.0}}
    assert _is_oa_ironclad(oa, adjusted_oas=aoas) is False


# ============================================================ summarize


def test_summarize_default_none_uses_raw():
    """summarize 默认 adjusted=None → dimensions 用 raw 值"""
    pcs = [_pc(1, "structure_similarity", 100.0, True)]
    oas = []
    summary = summarize(
        pcs,
        oas,
        per_dim_max={"structure_similarity": 100.0},
        ironclad_dims=["structure_similarity"],
        formula_total=85.0,
        formula_level="high",
        has_ironclad=True,
    )
    dim = summary["dimensions"]["structure_similarity"]
    assert dim["max_score"] == 100.0
    assert dim["ironclad_count"] == 1
    assert dim["top_k_examples"][0]["score"] == 100.0
    assert dim["top_k_examples"][0]["is_ironclad"] is True


def test_summarize_with_adjusted_uses_adjusted_score():
    """summarize 传入 adjusted dict → dimensions 用 adjusted 值"""
    pcs = [_pc(1, "structure_similarity", 100.0, True)]
    oas = []
    apcs = {1: {"score": 0.0, "is_ironclad": False}}
    summary = summarize(
        pcs,
        oas,
        per_dim_max={"structure_similarity": 0.0},  # adjusted per_dim_max
        ironclad_dims=[],
        formula_total=0.0,
        formula_level="low",
        has_ironclad=False,
        adjusted_pcs=apcs,
        adjusted_oas={},
    )
    dim = summary["dimensions"]["structure_similarity"]
    assert dim["ironclad_count"] == 0
    # top_k example 也消费 adjusted score + iron
    assert dim["top_k_examples"][0]["score"] == 0.0
    assert dim["top_k_examples"][0]["is_ironclad"] is False


def test_summarize_global_oa_with_adjusted_score():
    """global 型 OA(style)消费 adjusted_oas[oa.id].score"""
    pcs = []
    oas = [_oa(20, "style", 76.5)]
    aoas = {20: {"score": 0.0, "has_iron_evidence": False}}
    summary = summarize(
        pcs,
        oas,
        per_dim_max={"style": 0.0},
        ironclad_dims=[],
        formula_total=0.0,
        formula_level="low",
        has_ironclad=False,
        adjusted_pcs={},
        adjusted_oas=aoas,
    )
    dim = summary["dimensions"]["style"]
    assert dim["top_k_examples"][0]["score"] == 0.0
