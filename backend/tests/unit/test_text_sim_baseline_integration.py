"""L1 - text_sim_impl.aggregator + baseline 段级集成 (detect-tender-baseline §3.4)

覆盖 spec ADD Req "4 高优 detector 接入 baseline 注入点" 段级行为:
- ① tender 命中段不升 ironclad(段仍计入 score)
- ② consensus 命中段不升 ironclad
- ③ baseline_source='none' 且原触发条件成立时 MUST 升 ironclad(原行为不变)
- ④ L3 ≤2 投标方时 MUST 仍升 ironclad(基线缺失 ≠ 信号无效)
- ⑤ PC 内部分段命中 baseline 时按未命中段判 ironclad
- 段级 baseline_matched / baseline_source 写入 samples
- PC 顶级 baseline_source 取最强 source(tender > consensus > none)
- baseline_resolver get_excluded_segment_hashes_with_source 三级降级
"""

from __future__ import annotations

import hashlib

import pytest

from app.services.detect import baseline_resolver
from app.services.detect.agents.text_sim_impl.aggregator import (
    aggregate_pair_score,
    build_evidence_json,
    compute_is_ironclad,
)
from app.services.detect.agents.text_sim_impl.models import ParaPair
from app.services.detect.agents.text_sim_impl.tfidf import _normalize


def _seg_hash(text: str) -> str:
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


def _exact_pair(text_a: str, idx: int = 0) -> ParaPair:
    return ParaPair(
        a_idx=idx,
        b_idx=idx,
        a_text=text_a,
        b_text=text_a,
        sim=1.0,
        match_kind="exact_match",
    )


# ≥50 字归一化后非 baseline 段(默认会触发 ironclad)
LONG_TEXT_A = (
    "本项目按照招标文件第三章技术规范要求采用BIM建模流程"
    "并由项目经理统筹协调监理工程师每周例会推进工序流转"
    "确保按期保质交付。"
)
# ≥50 字归一化后 baseline 段 #1(假设是模板)
LONG_TEXT_TEMPLATE = (
    "投标人就上述项目向贵单位提交投标文件并承诺遵守本招标文件中"
    "的所有条款条件并自开标日起六十日内不可撤销有效。"
)
# ≥50 字归一化后 baseline 段 #2(用于 consensus 测试)
LONG_TEXT_TEMPLATE_2 = (
    "本投标人按招标文件要求按时提交完整密封的报价文件并自愿承担"
    "因本投标文件内容真实性造成的一切法律责任和后果不可撤回。"
)


def _assert_normalized_len_at_least(text: str, n: int) -> None:
    actual = len(_normalize(text))
    assert actual >= n, f"text 归一化后长度 {actual} < {n}: {_normalize(text)!r}"


# 三段 fixture 在 module 加载时自检长度,避免后续测试假阳/假阴
_assert_normalized_len_at_least(LONG_TEXT_A, 50)
_assert_normalized_len_at_least(LONG_TEXT_TEMPLATE, 50)
_assert_normalized_len_at_least(LONG_TEXT_TEMPLATE_2, 50)


# ============================================================ ① tender 命中段不升 ironclad


def test_ironclad_skipped_when_only_baseline_matched_segment():
    """单段 ≥50 字 exact_match,但段 hash ∈ baseline → is_ironclad=False(段被跳过)。"""
    p = _exact_pair(LONG_TEXT_TEMPLATE)
    excluded = {_seg_hash(LONG_TEXT_TEMPLATE)}
    assert (
        compute_is_ironclad(
            {}, pairs=[p], baseline_excluded_segment_hashes=excluded
        )
        is False
    )


def test_ironclad_skipped_with_consensus_excluded_set():
    """consensus 命中段同样被跳过(consensus / tender 在 excluded set 内不区分)。"""
    p = _exact_pair(LONG_TEXT_TEMPLATE_2)
    excluded = {_seg_hash(LONG_TEXT_TEMPLATE_2)}
    assert (
        compute_is_ironclad(
            {}, pairs=[p], baseline_excluded_segment_hashes=excluded
        )
        is False
    )


# ============================================================ ③ baseline_source='none' 时原行为不变


def test_ironclad_triggers_when_baseline_excluded_set_empty():
    """baseline 集为空(L3 ≤2 投标方场景) → ≥50 字 exact_match 仍 MUST 升 ironclad。"""
    p = _exact_pair(LONG_TEXT_A)
    assert compute_is_ironclad({}, pairs=[p], baseline_excluded_segment_hashes=set()) is True


def test_ironclad_triggers_when_baseline_arg_none_legacy():
    """老调用不传 baseline_excluded_segment_hashes → 行为完全等价于 §3 前。"""
    p = _exact_pair(LONG_TEXT_A)
    assert compute_is_ironclad({}, pairs=[p]) is True


# ============================================================ ⑤ 部分命中不豁免整 PC


def test_partial_baseline_match_still_triggers_ironclad():
    """PC 内 2 段:1 段 baseline + 1 段非 baseline ≥50 字 → is_ironclad=True
    (按未命中段判定,部分命中不豁免整 PC,spec scenario)。"""
    pairs = [
        _exact_pair(LONG_TEXT_TEMPLATE, idx=0),  # baseline 段
        _exact_pair(LONG_TEXT_A, idx=1),  # 非 baseline ≥50 字
    ]
    excluded = {_seg_hash(LONG_TEXT_TEMPLATE)}
    assert (
        compute_is_ironclad(
            {}, pairs=pairs, baseline_excluded_segment_hashes=excluded
        )
        is True
    )


def test_all_baseline_matched_no_ironclad():
    """全部 ≥50 字 exact_match 段都 ∈ baseline → is_ironclad=False。"""
    pairs = [
        _exact_pair(LONG_TEXT_TEMPLATE, idx=0),
        _exact_pair(LONG_TEXT_TEMPLATE_2, idx=1),
    ]
    excluded = {
        _seg_hash(LONG_TEXT_TEMPLATE),
        _seg_hash(LONG_TEXT_TEMPLATE_2),
    }
    assert (
        compute_is_ironclad(
            {}, pairs=pairs, baseline_excluded_segment_hashes=excluded
        )
        is False
    )


# ============================================================ degraded 模式不受 baseline 影响


def test_ironclad_degraded_returns_false_regardless_of_baseline():
    """degraded=True → 始终 False;baseline 参数不影响降级行为。"""
    p = _exact_pair(LONG_TEXT_A)
    assert (
        compute_is_ironclad(
            {},
            pairs=[p],
            degraded=True,
            baseline_excluded_segment_hashes=set(),
        )
        is False
    )


# ============================================================ plagiarism 路径不受 baseline 干扰


def test_plagiarism_ironclad_unaffected_by_baseline_set():
    """plag ≥3 走 LLM cosine 路径,与 baseline (作用于 hash 段) 互不干涉。"""
    pairs = [
        ParaPair(a_idx=i, b_idx=i, a_text=f"a{i}", b_text=f"b{i}", sim=0.8)
        for i in range(3)
    ]
    judgments = {0: "plagiarism", 1: "plagiarism", 2: "plagiarism"}
    # 即使 excluded 集合不空,也不影响 plagiarism 路径
    assert (
        compute_is_ironclad(
            judgments,
            pairs=pairs,
            baseline_excluded_segment_hashes={"some_hash"},
        )
        is True
    )


# ============================================================ aggregate_pair_score 不受 baseline 影响


def test_score_unchanged_when_baseline_excluded():
    """段被跳过 ironclad 触发,但 score 仍 MUST 计入(spec 段级语义)。"""
    p = _exact_pair(LONG_TEXT_TEMPLATE)
    score = aggregate_pair_score([p], {})
    # exact_match 权重 1.0:1.0 * 100 * 1.0 = 100,max=mean=100 → 100
    assert score == 100.0


# ============================================================ build_evidence_json 段级字段


def test_evidence_samples_include_baseline_matched_per_segment():
    """samples[i] MUST 含 baseline_matched + baseline_source 段级字段。"""
    pairs = [
        _exact_pair(LONG_TEXT_TEMPLATE, idx=0),  # baseline (tender)
        _exact_pair(LONG_TEXT_A, idx=1),  # 非 baseline
    ]
    hash_to_src = {_seg_hash(LONG_TEXT_TEMPLATE): "tender"}
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        threshold=0.7,
        pairs=pairs,
        judgments={},
        ai_meta=None,
        baseline_hash_to_source=hash_to_src,
    )
    samples = ev["samples"]
    assert samples[0]["baseline_matched"] is True
    assert samples[0]["baseline_source"] == "tender"
    assert samples[1]["baseline_matched"] is False
    assert samples[1]["baseline_source"] == "none"


def test_evidence_pc_baseline_source_takes_strongest_source():
    """PC 顶级 baseline_source 取所有命中段的最强(tender > consensus)。"""
    pairs = [
        _exact_pair(LONG_TEXT_TEMPLATE, idx=0),  # tender
        _exact_pair(LONG_TEXT_TEMPLATE_2, idx=1),  # consensus
    ]
    hash_to_src = {
        _seg_hash(LONG_TEXT_TEMPLATE): "tender",
        _seg_hash(LONG_TEXT_TEMPLATE_2): "consensus",
    }
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        threshold=0.7,
        pairs=pairs,
        judgments={},
        ai_meta=None,
        baseline_hash_to_source=hash_to_src,
    )
    assert ev["baseline_source"] == "tender"


def test_evidence_pc_baseline_source_consensus_only():
    pairs = [_exact_pair(LONG_TEXT_TEMPLATE, idx=0)]
    hash_to_src = {_seg_hash(LONG_TEXT_TEMPLATE): "consensus"}
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        threshold=0.7,
        pairs=pairs,
        judgments={},
        ai_meta=None,
        baseline_hash_to_source=hash_to_src,
    )
    assert ev["baseline_source"] == "consensus"


def test_evidence_pc_baseline_source_none_when_no_match():
    """无段命中 baseline → PC 顶级 baseline_source='none'。"""
    pairs = [_exact_pair(LONG_TEXT_A, idx=0)]
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        threshold=0.7,
        pairs=pairs,
        judgments={},
        ai_meta=None,
        baseline_hash_to_source={"unrelated_hash": "tender"},
    )
    assert ev["baseline_source"] == "none"


def test_evidence_warnings_propagated_l3():
    """baseline_warnings 数组写入 evidence_json.warnings(供前端 L3 警示条用)。"""
    pairs = [_exact_pair(LONG_TEXT_A, idx=0)]
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        threshold=0.7,
        pairs=pairs,
        judgments={},
        ai_meta=None,
        baseline_warnings=["baseline_unavailable_low_bidder_count"],
    )
    assert ev["warnings"] == ["baseline_unavailable_low_bidder_count"]


def test_evidence_default_baseline_source_none_when_arg_omitted():
    """老调用不传 baseline_hash_to_source → evidence.baseline_source='none' + warnings=[]。"""
    pairs = [_exact_pair(LONG_TEXT_A, idx=0)]
    ev = build_evidence_json(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        threshold=0.7,
        pairs=pairs,
        judgments={},
        ai_meta=None,
    )
    assert ev["baseline_source"] == "none"
    assert ev["warnings"] == []
    # samples 默认 baseline_matched=False / baseline_source='none'
    assert ev["samples"][0]["baseline_matched"] is False
    assert ev["samples"][0]["baseline_source"] == "none"


# ============================================================ baseline_resolver.get_excluded_segment_hashes_with_source


class _FakeSession:
    pass


@pytest.mark.asyncio
async def test_get_excluded_segment_hashes_l1_tender(monkeypatch):
    """L1 tender 路径:返回 hash → 'tender' 映射 + baseline_source='tender'。"""

    async def _tender(session, pid):
        return {"h_tender_1", "h_tender_2"}

    async def _bidder_count(session, pid):
        return 4

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_segment_hashes", _tender
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _bidder_count
    )

    res = await baseline_resolver.get_excluded_segment_hashes_with_source(
        _FakeSession(), 1, "text_similarity"
    )
    assert res.baseline_source == "tender"
    assert set(res.hash_to_source.keys()) == {"h_tender_1", "h_tender_2"}
    assert all(v == "tender" for v in res.hash_to_source.values())
    assert res.warnings == []


@pytest.mark.asyncio
async def test_get_excluded_segment_hashes_l2_consensus(monkeypatch):
    """L2 共识路径:返回 hash → 'consensus' 映射。"""

    async def _tender(session, pid):
        return set()

    async def _segs_by_role(session, pid):
        return {
            10: {"technical": {"h_c1"}},
            20: {"technical": {"h_c1"}},
            30: {"technical": {"h_c1"}},
        }

    async def _bidder_count(session, pid):
        return 3

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_segment_hashes", _tender
    )
    monkeypatch.setattr(
        baseline_resolver, "_load_bidder_segment_hashes_by_role", _segs_by_role
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _bidder_count
    )

    res = await baseline_resolver.get_excluded_segment_hashes_with_source(
        _FakeSession(), 1, "text_similarity"
    )
    assert res.baseline_source == "consensus"
    assert res.hash_to_source == {"h_c1": "consensus"}


@pytest.mark.asyncio
async def test_get_excluded_segment_hashes_l3_two_bidders_warns(monkeypatch):
    """L3 ≤2 投标方:返回空 hash + warnings='baseline_unavailable_low_bidder_count'。"""

    async def _tender(session, pid):
        return set()

    async def _bidder_count(session, pid):
        return 2

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_segment_hashes", _tender
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _bidder_count
    )

    res = await baseline_resolver.get_excluded_segment_hashes_with_source(
        _FakeSession(), 1, "text_similarity"
    )
    assert res.hash_to_source == {}
    assert res.baseline_source == "none"
    assert baseline_resolver.WARN_LOW_BIDDER in res.warnings


@pytest.mark.asyncio
async def test_get_excluded_segment_hashes_boq_no_consensus(monkeypatch):
    """BOQ 维度无 tender → none(不走 L2 共识,D5)。"""

    async def _boq(session, pid):
        return set()

    async def _bidder_count(session, pid):
        return 5

    monkeypatch.setattr(
        baseline_resolver, "_load_tender_boq_hashes", _boq
    )
    monkeypatch.setattr(
        baseline_resolver, "_count_alive_bidders", _bidder_count
    )

    res = await baseline_resolver.get_excluded_segment_hashes_with_source(
        _FakeSession(), 1, "price_consistency"
    )
    assert res.hash_to_source == {}
    assert res.baseline_source == "none"
    # BOQ 维度无 tender 时不出 L3 警示(L3 仅适用于 segment 维度)
    assert res.warnings == []
