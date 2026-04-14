"""L1 - text_sim_impl.aggregator 单元测试 (C7)"""

from __future__ import annotations

from app.services.detect.agents.text_sim_impl.aggregator import (
    aggregate_pair_score,
    build_evidence_json,
    compute_is_ironclad,
)
from app.services.detect.agents.text_sim_impl.models import ParaPair


def _pair(idx: int, sim: float = 0.9) -> ParaPair:
    return ParaPair(a_idx=idx, b_idx=idx, a_text=f"a{idx}", b_text=f"b{idx}", sim=sim)


# ---------- aggregate_pair_score ----------

def test_aggregate_empty_returns_zero():
    assert aggregate_pair_score([], {}) == 0.0


def test_aggregate_all_plagiarism_high_score():
    pairs = [_pair(i, sim=0.9) for i in range(3)]
    judgments = {0: "plagiarism", 1: "plagiarism", 2: "plagiarism"}
    # score_i = 0.9*100*1.0 = 90; max=90 mean=90; final=90
    assert aggregate_pair_score(pairs, judgments) == 90.0


def test_aggregate_all_generic_low_score():
    pairs = [_pair(i, sim=0.9) for i in range(3)]
    judgments = {0: "generic", 1: "generic", 2: "generic"}
    # score_i = 0.9*100*0.2 = 18; max=mean=18; final=18
    assert aggregate_pair_score(pairs, judgments) == 18.0


def test_aggregate_degraded_none_weight():
    pairs = [_pair(i, sim=0.8) for i in range(2)]
    # judgments 空 → 全按 None 权重 0.3
    score = aggregate_pair_score(pairs, {})
    # 0.8*100*0.3 = 24
    assert score == 24.0


def test_aggregate_mixed_max_weighted_more():
    # 1 个 plagiarism 高 + 2 个 generic 低,max=plagiarism 权重更大
    pairs = [_pair(0, 0.95), _pair(1, 0.70), _pair(2, 0.70)]
    judgments = {0: "plagiarism", 1: "generic", 2: "generic"}
    # scored = [95*1.0=95, 70*0.2=14, 70*0.2=14] → max=95 mean=41
    # final = 95*0.7 + 41*0.3 = 66.5 + 12.3 = 78.8
    score = aggregate_pair_score(pairs, judgments)
    assert 77 <= score <= 80


# ---------- compute_is_ironclad ----------

def test_is_ironclad_empty_judgments_false():
    assert compute_is_ironclad({}) is False


def test_is_ironclad_three_plagiarism_true():
    j = {0: "plagiarism", 1: "plagiarism", 2: "plagiarism", 3: "generic", 4: "generic"}
    assert compute_is_ironclad(j) is True


def test_is_ironclad_ratio_50_true():
    j = {0: "plagiarism", 1: "plagiarism", 2: "generic", 3: "generic"}
    # 2/4 = 0.5 → 触发
    assert compute_is_ironclad(j) is True


def test_is_ironclad_two_plag_below_threshold_false():
    j = {0: "plagiarism", 1: "plagiarism", 2: "generic", 3: "generic", 4: "generic"}
    # 2/5 = 0.4 < 0.5,< 3 绝对 → false
    assert compute_is_ironclad(j) is False


# ---------- build_evidence_json ----------

def test_evidence_json_normal():
    pairs = [_pair(0, 0.95), _pair(1, 0.85)]
    judgments = {0: "plagiarism", 1: "generic"}
    ai_meta = {"overall": "抄袭", "confidence": "high"}
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        threshold=0.70,
        pairs=pairs,
        judgments=judgments,
        ai_meta=ai_meta,
    )
    assert ev["algorithm"] == "tfidf_cosine_v1"
    assert ev["degraded"] is False
    assert ev["pairs_plagiarism"] == 1
    assert ev["pairs_generic"] == 1
    assert ev["pairs_template"] == 0
    assert ev["ai_judgment"]["confidence"] == "high"
    assert len(ev["samples"]) == 2
    assert ev["samples"][0]["label"] == "plagiarism"


def test_evidence_json_degraded():
    pairs = [_pair(0, 0.8), _pair(1, 0.7)]
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        threshold=0.70,
        pairs=pairs,
        judgments={},
        ai_meta=None,
    )
    assert ev["degraded"] is True
    assert ev["ai_judgment"] is None
    # 降级:all pairs attributed to generic count
    assert ev["pairs_plagiarism"] == 0
    assert ev["pairs_template"] == 0
    assert ev["pairs_generic"] == 2
    # samples 仍保留
    assert len(ev["samples"]) == 2
    assert ev["samples"][0]["label"] is None


def test_evidence_json_samples_truncated_to_10():
    pairs = [_pair(i, sim=0.9 - i * 0.01) for i in range(25)]
    judgments = {i: "plagiarism" for i in range(25)}
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        threshold=0.70,
        pairs=pairs,
        judgments=judgments,
        ai_meta={"overall": "", "confidence": ""},
    )
    assert len(ev["samples"]) == 10
    assert ev["pairs_total"] == 25
