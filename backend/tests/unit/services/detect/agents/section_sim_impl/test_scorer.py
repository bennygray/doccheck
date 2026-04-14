"""L1 - scorer 单元测试 (C8)

重点验证"复用 C7 text_sim_impl" 的 wiring;算法本身已在 C7 L1 测过,不重复。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services.detect.agents.section_sim_impl import scorer
from app.services.detect.agents.section_sim_impl.models import (
    ChapterBlock,
    ChapterPair,
)
from app.services.detect.agents.text_sim_impl.models import ParaPair
from app.services.llm.base import LLMError, LLMResult


def _ch(idx, title, paras):
    return ChapterBlock(
        idx=idx, title=title, paragraphs=tuple(paras),
        total_chars=sum(len(p) for p in paras),
    )


def _cp(a_idx, b_idx, title_sim=0.5, aligned_by="title"):
    return ChapterPair(
        a_idx=a_idx, b_idx=b_idx, title_sim=title_sim, aligned_by=aligned_by
    )


class _StubProvider:
    name = "stub"

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def complete(self, messages, **kwargs):
        self.calls += 1
        item = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        text, err = item
        return LLMResult(text=text or "", error=err)


def _sync_future(fn, *args):
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    try:
        fut.set_result(fn(*args))
    except Exception as e:
        fut.set_exception(e)
    return fut


def _patch_sync_executor(monkeypatch):
    monkeypatch.setattr(
        asyncio, "get_running_loop",
        lambda: SimpleNamespace(
            run_in_executor=lambda ex, fn, *a: _sync_future(fn, *a)
        ),
    )


# ---------- score_all_chapter_pairs ----------

@pytest.mark.asyncio
async def test_score_all_empty_chapter_pairs(monkeypatch):
    """无对齐章节对 → 返空 + LLM 未调用。"""
    chapters_a = [_ch(0, "ch0", ["p0"])]
    chapters_b = [_ch(0, "ch0", ["p0"])]
    provider = _StubProvider([("{}", None)])
    _patch_sync_executor(monkeypatch)

    results, selected, judgments, ai_meta = await scorer.score_all_chapter_pairs(
        chapters_a, chapters_b, [], provider, "A", "B", "technical"
    )
    assert results == []
    assert selected == []
    assert judgments == {}
    # 无选中 pair,LLM 不调用
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_score_all_calls_c7_modules(monkeypatch):
    """spy 验证调用了 text_sim_impl.tfidf + llm_judge + aggregator。"""
    # mock tfidf.compute_pair_similarity 返 fixed pairs
    from app.services.detect.agents.section_sim_impl import scorer as scorer_mod

    def fake_tfidf(a, b, th, mx):
        return [ParaPair(a_idx=0, b_idx=0, a_text="x", b_text="y", sim=0.9)]

    monkeypatch.setattr(scorer_mod.c7_tfidf, "compute_pair_similarity", fake_tfidf)
    _patch_sync_executor(monkeypatch)

    llm_text = json.dumps({
        "pairs": [{"idx": 0, "judgment": "plagiarism"}],
        "overall": "mock", "confidence": "high",
    })
    provider = _StubProvider([(llm_text, None)])

    chapters_a = [_ch(0, "ch0", ["p0"]), _ch(1, "ch1", ["p1"])]
    chapters_b = [_ch(0, "ch0", ["p0"]), _ch(1, "ch1", ["p1"])]
    pairs = [_cp(0, 0), _cp(1, 1)]

    results, selected, judgments, ai_meta = await scorer.score_all_chapter_pairs(
        chapters_a, chapters_b, pairs, provider, "A", "B", "tech"
    )
    # 2 章节 × 1 段落对 = 2 段落对进 selected(若 < max_pairs_to_llm=30)
    assert len(selected) == 2
    assert provider.calls == 1  # 一次 LLM 调用合并所有章节
    assert len(results) == 2
    # 所有章节都得 plagiarism judgement → chapter_score 高
    assert all(r.chapter_score > 0 for r in results)


@pytest.mark.asyncio
async def test_score_all_llm_timeout_degrades(monkeypatch):
    from app.services.detect.agents.section_sim_impl import scorer as scorer_mod

    monkeypatch.setattr(
        scorer_mod.c7_tfidf, "compute_pair_similarity",
        lambda a, b, th, mx: [
            ParaPair(a_idx=0, b_idx=0, a_text="x", b_text="y", sim=0.9)
        ],
    )
    _patch_sync_executor(monkeypatch)

    provider = _StubProvider([("", LLMError(kind="timeout", message="t"))])
    chapters_a = [_ch(0, "ch0", ["p0"])]
    chapters_b = [_ch(0, "ch0", ["p0"])]
    pairs = [_cp(0, 0)]

    results, _, judgments, ai_meta = await scorer.score_all_chapter_pairs(
        chapters_a, chapters_b, pairs, provider, "A", "B", "tech"
    )
    # LLM timeout → judgments 空,ai_meta 为 None
    assert judgments == {}
    assert ai_meta is None
    # 降级路径 chapter_score 仍计算(按 None 权重 0.3)
    assert results[0].chapter_score > 0
    assert results[0].is_chapter_ironclad is False  # 降级不铁证


# ---------- aggregate_pair_level ----------

def test_aggregate_pair_empty():
    assert scorer.aggregate_pair_level([]) == (0.0, False)


def test_aggregate_pair_max_mean():
    from app.services.detect.agents.section_sim_impl.models import ChapterScoreResult

    results = [
        ChapterScoreResult(
            chapter_pair_idx=0, a_idx=0, b_idx=0, a_title="a", b_title="b",
            title_sim=0.5, aligned_by="title",
            chapter_score=80.0, is_chapter_ironclad=True, plagiarism_count=5,
            para_pair_count=5, samples=[],
        ),
        ChapterScoreResult(
            chapter_pair_idx=1, a_idx=1, b_idx=1, a_title="a", b_title="b",
            title_sim=0.2, aligned_by="index",
            chapter_score=20.0, is_chapter_ironclad=False, plagiarism_count=0,
            para_pair_count=2, samples=[],
        ),
    ]
    score, is_iron = scorer.aggregate_pair_level(results)
    # max=80 mean=50; score = 80*0.6 + 50*0.4 = 48 + 20 = 68
    assert score == 68.0
    assert is_iron is True  # 任一章节 ironclad
