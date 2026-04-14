"""L1 - fallback 单元测试 (C8)

验证降级分支的 wiring 和 evidence 字段。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services.detect.agents.section_sim_impl import fallback
from app.services.detect.agents.text_sim_impl.models import ParaPair
from app.services.llm.base import LLMError, LLMResult


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


@pytest.mark.asyncio
async def test_fallback_normal_llm_success(monkeypatch):
    # mock tfidf
    monkeypatch.setattr(
        fallback.c7_tfidf, "compute_pair_similarity",
        lambda a, b, th, mx: [
            ParaPair(a_idx=0, b_idx=0, a_text="x", b_text="y", sim=0.9)
        ],
    )
    _patch_sync_executor(monkeypatch)

    llm_text = json.dumps({
        "pairs": [{"idx": 0, "judgment": "plagiarism"}],
        "overall": "降级命中", "confidence": "high",
    })
    provider = _StubProvider([(llm_text, None)])

    score, is_iron, evidence = await fallback.run_doc_level_fallback(
        paragraphs_a=["para_a"],
        paragraphs_b=["para_b"],
        doc_role="technical",
        doc_id_a=1, doc_id_b=2,
        bidder_a_name="A", bidder_b_name="B",
        llm_provider=provider,
        degrade_reason="章节切分失败(chapters_a=0, chapters_b=2, < 3)",
        chapters_a_count=0, chapters_b_count=2,
    )
    assert evidence["algorithm"] == "tfidf_cosine_fallback_to_doc"
    assert evidence["degraded_to_doc_level"] is True
    assert evidence["degrade_reason"] == "章节切分失败(chapters_a=0, chapters_b=2, < 3)"
    assert evidence["chapters_a_count"] == 0
    assert evidence["chapters_b_count"] == 2
    assert evidence["aligned_count"] == 0
    assert evidence["index_fallback_count"] == 0
    assert evidence["chapter_pairs"] == []
    # LLM 成功时 degraded=false(LLM 侧)
    assert evidence["degraded"] is False
    # 1/1 plagiarism = 100% 占比 → ironclad(C7 规则:plag >= 3 OR >= 50%)
    assert is_iron is True


@pytest.mark.asyncio
async def test_fallback_llm_timeout_double_degrade(monkeypatch):
    """章节切分失败 + LLM timeout → 双重降级并存。"""
    monkeypatch.setattr(
        fallback.c7_tfidf, "compute_pair_similarity",
        lambda a, b, th, mx: [
            ParaPair(a_idx=0, b_idx=0, a_text="x", b_text="y", sim=0.9)
        ],
    )
    _patch_sync_executor(monkeypatch)

    provider = _StubProvider([("", LLMError(kind="timeout", message="t"))])

    score, is_iron, evidence = await fallback.run_doc_level_fallback(
        paragraphs_a=["a"], paragraphs_b=["b"],
        doc_role="tech", doc_id_a=1, doc_id_b=2,
        bidder_a_name="A", bidder_b_name="B",
        llm_provider=provider,
        degrade_reason="两侧章节数都为 0",
        chapters_a_count=0, chapters_b_count=0,
    )
    # 两种降级并存
    assert evidence["degraded_to_doc_level"] is True
    assert evidence["degraded"] is True  # LLM 侧降级
    assert evidence["ai_judgment"] is None
    assert is_iron is False


@pytest.mark.asyncio
async def test_fallback_no_pairs_zero_score(monkeypatch):
    """整文档 TF-IDF 也筛不出 → score=0,不调 LLM。"""
    monkeypatch.setattr(
        fallback.c7_tfidf, "compute_pair_similarity",
        lambda a, b, th, mx: [],
    )
    _patch_sync_executor(monkeypatch)

    provider = _StubProvider([("should not call", None)])

    score, is_iron, evidence = await fallback.run_doc_level_fallback(
        paragraphs_a=["a"], paragraphs_b=["b"],
        doc_role="tech", doc_id_a=1, doc_id_b=2,
        bidder_a_name="A", bidder_b_name="B",
        llm_provider=provider,
        degrade_reason="独立文档",
        chapters_a_count=0, chapters_b_count=0,
    )
    assert score == 0.0
    assert is_iron is False
    # LLM 未被调用
    assert provider.calls == 0
    assert evidence["degraded"] is False  # LLM 未调用,不算降级
