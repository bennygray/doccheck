"""L1 - section_similarity baseline 接入 (detect-tender-baseline §4.3)

覆盖 spec ADD Req "4 高优 detector 接入 baseline 注入点" 章节级行为:
- ① 章节标题 hash ∈ baseline → is_chapter_ironclad=False(整章节是模板,LLM 判 plag 也不顶铁证)
- ② 章节内段级 baseline 命中 → sample.baseline_matched=true + 段级 ironclad 跳过(§3 同 path)
- ③ 章节内段级联合判定:章节标题不命中 + 段全命中 → 段级 skip 仍触发(若有未命中段且 plag ≥3)
- ④ PC 顶级 baseline_source = 章节级 + 段级 source 取最强(tender > consensus > none)
- ⑤ baseline 空集时(无 tender + L3 ≤2 投标方)→ 行为完全等价于 §4 前(部分命中不豁免整 PC)
- ⑥ aggregate_pc_baseline_source 跨章节聚合
- ⑦ 老调用兼容(不传 baseline_hash_to_source kwarg)

策略:patch run_isolated 跳过子进程,patch LLM,直接调 score_all_chapter_pairs。
"""

from __future__ import annotations

import asyncio
import hashlib

import pytest

from app.services.detect.agents.section_sim_impl import scorer
from app.services.detect.agents.section_sim_impl.models import (
    ChapterBlock,
    ChapterPair,
    ChapterScoreResult,
)
from app.services.detect.agents.text_sim_impl.models import ParaPair
from app.services.detect.agents.text_sim_impl.tfidf import _normalize


def _seg_hash(text: str) -> str:
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


def _ch(idx: int, title: str, paras: list[str]) -> ChapterBlock:
    return ChapterBlock(
        idx=idx,
        title=title,
        paragraphs=tuple(paras),
        total_chars=sum(len(p) for p in paras),
    )


def _cp(a_idx: int, b_idx: int, title_sim: float = 0.95) -> ChapterPair:
    return ChapterPair(
        a_idx=a_idx, b_idx=b_idx, title_sim=title_sim, aligned_by="title"
    )


# ≥50 字归一化的章节标题(模拟 baseline-命中标题)
TEMPLATE_TITLE = (
    "第二章 投标人就上述项目向招标人提交投标文件并承诺遵守"
    "本招标文件中的所有条款条件并自开标日起六十日内不可撤销有效"
)
# ≥50 字归一化的段(可作为 sample 段级 baseline 命中验证)
TEMPLATE_PARA = (
    "本投标人按招标文件要求提交完整密封报价并自愿承担因本投标"
    "文件内容真实性产生的一切法律责任后果不可撤回"
)
# 非 baseline 段
PLAGIARISM_PARA = (
    "项目核心采用先进 AI 技术结合机器学习算法识别投标文件中的"
    "串通围标行为为发标方提供合规审查辅助决策依据有用"
)


def _assert_norm_len_at_least(text: str, n: int) -> None:
    actual = len(_normalize(text))
    assert actual >= n, f"text 归一化后长度 {actual} < {n}: {_normalize(text)!r}"


_assert_norm_len_at_least(TEMPLATE_TITLE, 50)
_assert_norm_len_at_least(TEMPLATE_PARA, 50)
_assert_norm_len_at_least(PLAGIARISM_PARA, 50)


# ============================================================ scorer.score_all_chapter_pairs


def _patch_subprocess_to_inline(monkeypatch, fixed_pairs: list[list[ParaPair]]) -> None:
    """patch run_isolated 直接返指定的章节×对结果(跳过子进程 spawn)。"""
    async def _fake(fn, *args, **kw):
        # fn = compute_all_pair_sims_batch / chapter_pair_data, threshold, max_pairs
        # 返 fixed_pairs(对应 each chapter)
        return fixed_pairs

    monkeypatch.setattr(
        "app.services.detect.agents.section_sim_impl.scorer.run_isolated", _fake
    )


def _patch_llm_to_judgments(monkeypatch, judgments_by_idx: dict[int, str]) -> None:
    """patch llm_judge.call_llm_judge 返指定的 judgments + ai_meta。"""
    async def _fake(provider, name_a, name_b, doc_role, pairs):
        return judgments_by_idx, {"overall": "stub", "confidence": "high"}

    monkeypatch.setattr(
        "app.services.detect.agents.section_sim_impl.scorer.c7_llm_judge.call_llm_judge",
        _fake,
    )


@pytest.mark.asyncio
async def test_chapter_title_baseline_match_skips_ironclad(monkeypatch):
    """① 章节标题 hash ∈ baseline → is_chapter_ironclad=False
    (即使 LLM 判 plagiarism 也不顶铁证;章节是模板)。"""
    chapters_a = [_ch(0, TEMPLATE_TITLE, [PLAGIARISM_PARA] * 4)]
    chapters_b = [_ch(0, TEMPLATE_TITLE, [PLAGIARISM_PARA] * 4)]
    chapter_pairs = [_cp(0, 0)]

    # 段对全 plagiarism(>= 3 触发 LLM-route ironclad)
    para_pairs = [
        ParaPair(a_idx=i, b_idx=i, a_text=PLAGIARISM_PARA, b_text=PLAGIARISM_PARA, sim=0.9)
        for i in range(4)
    ]
    _patch_subprocess_to_inline(monkeypatch, [para_pairs])
    _patch_llm_to_judgments(monkeypatch, {0: "plagiarism", 1: "plagiarism", 2: "plagiarism", 3: "plagiarism"})

    baseline = {_seg_hash(TEMPLATE_TITLE): "tender"}
    results, _, _, _ = await scorer.score_all_chapter_pairs(
        chapters_a, chapters_b, chapter_pairs,
        llm_provider=None, bidder_a_name="A", bidder_b_name="B",
        doc_role="technical",
        baseline_hash_to_source=baseline,
    )
    assert len(results) == 1
    r = results[0]
    assert r.chapter_baseline_matched is True
    assert r.chapter_baseline_source == "tender"
    # LLM 全判 plagiarism 但章节标题命中 baseline → 不顶铁证
    assert r.is_chapter_ironclad is False


@pytest.mark.asyncio
async def test_segment_level_baseline_skips_ironclad(monkeypatch):
    """② 章节标题不在 baseline 但段级命中 → ≥50 字段被段级跳过"""
    custom_title = "第三章 项目实施方案技术架构"  # 不在 baseline
    chapters_a = [_ch(0, custom_title, [TEMPLATE_PARA])]
    chapters_b = [_ch(0, custom_title, [TEMPLATE_PARA])]
    chapter_pairs = [_cp(0, 0)]

    para_pairs = [
        ParaPair(
            a_idx=0, b_idx=0,
            a_text=TEMPLATE_PARA, b_text=TEMPLATE_PARA,
            sim=1.0, match_kind="exact_match",
        )
    ]
    _patch_subprocess_to_inline(monkeypatch, [para_pairs])
    _patch_llm_to_judgments(monkeypatch, {})

    # 段级 baseline 命中(标题不在 baseline)
    baseline = {_seg_hash(TEMPLATE_PARA): "tender"}
    results, _, _, _ = await scorer.score_all_chapter_pairs(
        chapters_a, chapters_b, chapter_pairs,
        llm_provider=None, bidder_a_name="A", bidder_b_name="B",
        doc_role="technical",
        baseline_hash_to_source=baseline,
    )
    r = results[0]
    assert r.chapter_baseline_matched is False
    # 段级跳过 → exact_match ≥50 字段被 baseline_excluded 路径跳过
    assert r.is_chapter_ironclad is False
    # samples 段级标记
    assert r.samples[0]["baseline_matched"] is True
    assert r.samples[0]["baseline_source"] == "tender"


@pytest.mark.asyncio
async def test_partial_baseline_match_still_triggers_ironclad(monkeypatch):
    """③ 章节内 1 段 baseline + 1 段非 baseline ≥50 字 exact_match → is_ironclad=True
    (按未命中段判定,部分命中不豁免整章节)。"""
    custom_title = "第三章 实施方案"  # 不在 baseline
    chapters_a = [_ch(0, custom_title, [TEMPLATE_PARA, PLAGIARISM_PARA])]
    chapters_b = [_ch(0, custom_title, [TEMPLATE_PARA, PLAGIARISM_PARA])]
    chapter_pairs = [_cp(0, 0)]

    para_pairs = [
        ParaPair(a_idx=0, b_idx=0, a_text=TEMPLATE_PARA, b_text=TEMPLATE_PARA, sim=1.0, match_kind="exact_match"),
        ParaPair(a_idx=1, b_idx=1, a_text=PLAGIARISM_PARA, b_text=PLAGIARISM_PARA, sim=1.0, match_kind="exact_match"),
    ]
    _patch_subprocess_to_inline(monkeypatch, [para_pairs])
    _patch_llm_to_judgments(monkeypatch, {})

    baseline = {_seg_hash(TEMPLATE_PARA): "tender"}
    results, _, _, _ = await scorer.score_all_chapter_pairs(
        chapters_a, chapters_b, chapter_pairs,
        llm_provider=None, bidder_a_name="A", bidder_b_name="B",
        doc_role="technical",
        baseline_hash_to_source=baseline,
    )
    r = results[0]
    # 章节标题不命中 + PLAGIARISM_PARA 段 ≥50 字 + 不在 baseline → 仍触发 ironclad
    assert r.chapter_baseline_matched is False
    assert r.is_chapter_ironclad is True
    # samples 标记差异化
    matched = [s for s in r.samples if s.get("baseline_matched")]
    unmatched = [s for s in r.samples if not s.get("baseline_matched")]
    assert len(matched) >= 1
    assert len(unmatched) >= 1


@pytest.mark.asyncio
async def test_no_baseline_legacy_behavior(monkeypatch):
    """⑦ 老调用不传 baseline_hash_to_source → 行为完全等价于 §4 前
    (chapter_baseline_source 默认 'none',is_chapter_ironclad 仅看 LLM)。"""
    chapters_a = [_ch(0, "Title", [PLAGIARISM_PARA] * 4)]
    chapters_b = [_ch(0, "Title", [PLAGIARISM_PARA] * 4)]
    chapter_pairs = [_cp(0, 0)]

    para_pairs = [
        ParaPair(a_idx=i, b_idx=i, a_text=PLAGIARISM_PARA, b_text=PLAGIARISM_PARA, sim=0.85)
        for i in range(4)
    ]
    _patch_subprocess_to_inline(monkeypatch, [para_pairs])
    _patch_llm_to_judgments(monkeypatch, {0: "plagiarism", 1: "plagiarism", 2: "plagiarism", 3: "plagiarism"})

    # 不传 baseline_hash_to_source
    results, _, _, _ = await scorer.score_all_chapter_pairs(
        chapters_a, chapters_b, chapter_pairs,
        llm_provider=None, bidder_a_name="A", bidder_b_name="B",
        doc_role="technical",
    )
    r = results[0]
    assert r.chapter_baseline_source == "none"
    assert r.chapter_baseline_matched is False
    # plag=4 ≥ 3 → ironclad(§4 前行为不变)
    assert r.is_chapter_ironclad is True
    for s in r.samples:
        assert s["baseline_matched"] is False
        assert s["baseline_source"] == "none"


# ============================================================ aggregate_pc_baseline_source


def _result_with(source: str = "none", samples: list[dict] | None = None) -> ChapterScoreResult:
    return ChapterScoreResult(
        chapter_pair_idx=0, a_idx=0, b_idx=0, a_title="t", b_title="t",
        title_sim=0.9, aligned_by="title",
        chapter_score=50.0, is_chapter_ironclad=False, plagiarism_count=0,
        para_pair_count=0, samples=samples or [],
        chapter_baseline_source=source,
        chapter_baseline_matched=(source != "none"),
    )


def test_aggregate_pc_baseline_source_strongest_chapter():
    """④ PC 顶级 baseline_source 取最强:tender > consensus > none。"""
    r1 = _result_with("consensus")
    r2 = _result_with("tender")
    assert scorer.aggregate_pc_baseline_source([r1, r2]) == "tender"


def test_aggregate_pc_baseline_source_segment_overrides_chapter_none():
    """章节标题 none + 内部 sample tender → PC 顶级 = tender。"""
    r = _result_with(
        "none",
        samples=[{"baseline_matched": True, "baseline_source": "consensus"}],
    )
    assert scorer.aggregate_pc_baseline_source([r]) == "consensus"


def test_aggregate_pc_baseline_source_all_none():
    r = _result_with("none", samples=[{"baseline_matched": False, "baseline_source": "none"}])
    assert scorer.aggregate_pc_baseline_source([r]) == "none"


def test_aggregate_pc_baseline_source_empty():
    assert scorer.aggregate_pc_baseline_source([]) == "none"


def test_aggregate_pc_baseline_source_segment_tender_beats_chapter_consensus():
    r = _result_with(
        "consensus",
        samples=[{"baseline_matched": True, "baseline_source": "tender"}],
    )
    assert scorer.aggregate_pc_baseline_source([r]) == "tender"


# ============================================================ ChapterScoreResult schema


def test_chapter_score_result_default_fields_legacy():
    """ChapterScoreResult 老调用兼容 — chapter_baseline_* 字段默认 'none'/False。"""
    r = ChapterScoreResult(
        chapter_pair_idx=0, a_idx=0, b_idx=0, a_title="t", b_title="t",
        title_sim=0.9, aligned_by="title",
        chapter_score=50.0, is_chapter_ironclad=False, plagiarism_count=0,
        para_pair_count=0,
    )
    assert r.chapter_baseline_source == "none"
    assert r.chapter_baseline_matched is False
