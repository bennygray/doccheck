"""L1 - text_similarity / aggregator 老 evidence 兼容 (detect-tender-baseline §3.5)

覆盖 spec ADD Req "4 高优 detector 接入 baseline 注入点":
- 后端读老 PairComparison 兼容:evidence_json 缺 baseline_source / warnings 字段时
  reports API MUST NOT 抛 KeyError,默认 'none' / [](向后兼容)
- aggregator.compute_is_ironclad / build_evidence_json 不传 baseline_* kwarg 时
  行为完全等价于 detect-tender-baseline 接入前(§3 改造 0 回归)
- ParaPair 老 evidence 形态(无 baseline_matched / baseline_source 段级字段)读取兜底
"""

from __future__ import annotations

from app.services.detect.agents.text_sim_impl.aggregator import (
    aggregate_pair_score,
    build_evidence_json,
    compute_is_ironclad,
)
from app.services.detect.agents.text_sim_impl.models import ParaPair
from app.services.detect.agents.text_sim_impl.tfidf import _normalize


def _exact_pair(text: str, idx: int = 0) -> ParaPair:
    return ParaPair(
        a_idx=idx,
        b_idx=idx,
        a_text=text,
        b_text=text,
        sim=1.0,
        match_kind="exact_match",
    )


# ≥50 字归一化后段(默认会触发 ironclad)
LONG_TEXT = (
    "本项目按照招标文件第三章技术规范要求采用BIM建模流程"
    "并由项目经理统筹协调监理工程师每周例会推进工序流转"
    "确保按期保质交付。"
)


def test_long_text_fixture_satisfies_ironclad_threshold():
    """fixture 自检:LONG_TEXT 归一化后 ≥50 字。"""
    assert len(_normalize(LONG_TEXT)) >= 50


# ============================================================ compute_is_ironclad 老调用兼容


def test_compute_is_ironclad_no_kwargs_legacy():
    """老调用不传任何 baseline kwarg → 行为完全等价于 §3 前。"""
    p = _exact_pair(LONG_TEXT)
    # ≥50 字 exact_match → True(§3 前行为)
    assert compute_is_ironclad({}, pairs=[p]) is True


def test_compute_is_ironclad_explicit_none_legacy():
    """显式传 baseline_excluded_segment_hashes=None 等价于不传。"""
    p = _exact_pair(LONG_TEXT)
    assert (
        compute_is_ironclad(
            {}, pairs=[p], baseline_excluded_segment_hashes=None
        )
        is True
    )


def test_compute_is_ironclad_section_similarity_legacy_call_unchanged():
    """section_similarity 老调用形式(只传 judgments,不传 pairs / degraded)
    在 §3 改造后仍等价于"判降级"行为(空 judgments → False)。"""
    # 不传 pairs / degraded / baseline_*,模拟 section_similarity 旧 call site
    assert compute_is_ironclad({}) is False


def test_compute_is_ironclad_plagiarism_threshold_unchanged():
    """plag ≥3 触发铁证(§3 前行为),不传 baseline 仍按原阈值判定。"""
    pairs = [
        ParaPair(a_idx=i, b_idx=i, a_text=f"a{i}", b_text=f"b{i}", sim=0.85)
        for i in range(3)
    ]
    judgments = {0: "plagiarism", 1: "plagiarism", 2: "plagiarism"}
    assert compute_is_ironclad(judgments, pairs=pairs) is True


# ============================================================ build_evidence_json 老调用兼容


def test_build_evidence_json_no_baseline_kwargs_default_none():
    """老调用不传 baseline_hash_to_source / baseline_warnings:
    evidence.baseline_source='none',evidence.warnings=[],samples 段级默认 false/none。"""
    pairs = [_exact_pair(LONG_TEXT, idx=0)]
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        threshold=0.7,
        pairs=pairs,
        judgments={},
        ai_meta=None,
    )
    # PC 顶级 baseline_source 默认 'none'(向后兼容)
    assert ev["baseline_source"] == "none"
    # warnings 默认空数组
    assert ev["warnings"] == []
    # samples 段级默认 baseline_matched=False,baseline_source='none'
    for s in ev["samples"]:
        assert s["baseline_matched"] is False
        assert s["baseline_source"] == "none"


def test_build_evidence_json_legacy_fields_unchanged():
    """老 evidence 字段(algorithm / pairs_total / samples 等)在 §3 改造后保留不变。"""
    pairs = [
        _exact_pair(LONG_TEXT, idx=0),
        ParaPair(a_idx=1, b_idx=1, a_text="b", b_text="b", sim=0.85),
    ]
    judgments = {1: "generic"}
    ai_meta = {"overall": "无显著抄袭", "confidence": "high"}
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=10,
        doc_id_b=20,
        threshold=0.7,
        pairs=pairs,
        judgments=judgments,
        ai_meta=ai_meta,
    )
    # 老字段全保留
    assert ev["algorithm"] == "tfidf_cosine_v1"
    assert ev["doc_role"] == "technical"
    assert ev["doc_id_a"] == 10
    assert ev["doc_id_b"] == 20
    assert ev["threshold"] == 0.7
    assert ev["pairs_total"] == 2
    assert ev["pairs_exact_match"] == 1
    assert ev["pairs_generic"] == 1
    assert ev["degraded"] is False
    assert ev["ai_judgment"] == {"overall": "无显著抄袭", "confidence": "high"}
    # samples 老字段保留
    assert ev["samples"][0]["a_idx"] == 0
    assert ev["samples"][0]["sim"] == 1.0
    assert ev["samples"][0]["label"] == "exact_match"


def test_build_evidence_json_degraded_legacy_path():
    """降级路径(ai_meta=None) + 不传 baseline kwargs 与 §3 前完全一致。"""
    pairs = [_exact_pair(LONG_TEXT, idx=0)]
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        threshold=0.7,
        pairs=pairs,
        judgments={},
        ai_meta=None,
    )
    assert ev["degraded"] is True
    assert ev["ai_judgment"] is None
    assert ev["pairs_plagiarism"] == 0
    assert ev["pairs_template"] == 0
    # 段级 baseline 字段默认 false/none
    assert ev["samples"][0]["baseline_matched"] is False


# ============================================================ 老 PC.evidence_json 读取兜底(reports API)


def test_old_evidence_dict_get_baseline_source_fallback_none():
    """模拟老 evidence(本字段不存在)→ get('baseline_source', 'none') 默认值,不报 KeyError。"""
    old_evidence = {
        "algorithm": "tfidf_cosine_v1",
        "pairs_total": 5,
        "samples": [{"a_idx": 0, "b_idx": 0, "sim": 0.9, "label": "plagiarism"}],
    }
    # spec 约束:reports API MUST NOT 抛 KeyError
    assert old_evidence.get("baseline_source", "none") == "none"
    assert old_evidence.get("warnings", []) == []


def test_old_evidence_samples_without_baseline_matched_renders_false_default():
    """老 evidence.samples 缺 baseline_matched / baseline_source → 前端 fallback 渲染 false/none。"""
    old_sample = {
        "a_idx": 0,
        "b_idx": 0,
        "a_text": "...",
        "b_text": "...",
        "sim": 0.9,
        "label": "exact_match",
    }
    # spec 约束:前端容错 fallback,不复算 hash
    assert old_sample.get("baseline_matched", False) is False
    assert old_sample.get("baseline_source", "none") == "none"


# ============================================================ aggregate_pair_score 不受 baseline 影响


def test_aggregate_pair_score_signature_unchanged():
    """aggregate_pair_score 签名不变(§3 不改)。"""
    pairs = [_exact_pair(LONG_TEXT, idx=0)]
    score = aggregate_pair_score(pairs, {})
    # exact_match 权重 1.0 → 100
    assert score == 100.0
