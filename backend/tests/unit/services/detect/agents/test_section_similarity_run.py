"""L1 - section_similarity Agent 主流程单测 (C8)

Mock segmenter + tfidf,验证 run() 串联逻辑:
- preflight 扩字数下限
- 章节切分成功 → 正常流
- 章节切分失败 → 走 fallback
- LLM timeout → 章节模式下的降级(evidence.degraded=true)
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.detect.agents import section_similarity as ss_mod
from app.services.detect.agents.text_sim_impl import segmenter as segmenter_mod
from app.services.detect.agents.text_sim_impl.models import ParaPair
from app.services.detect.context import AgentContext
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


def _bidder(id: int, name: str):
    return SimpleNamespace(id=id, name=name)


def _make_ctx(llm_provider=None):
    session = AsyncMock()
    session.add = lambda *a, **kw: None
    session.flush = AsyncMock()
    return AgentContext(
        project_id=1, version=1, agent_task=SimpleNamespace(),
        bidder_a=_bidder(10, "甲公司"), bidder_b=_bidder(20, "乙公司"),
        all_bidders=[], llm_provider=llm_provider, session=session,
    )


def _seg(total=800, doc_id=1, paras=None):
    if paras is None:
        paras = ["第一章 投标函", "p" * 300, "第二章 技术", "q" * 300]
    return segmenter_mod.SegmentResult(
        doc_role="technical", doc_id=doc_id,
        paragraphs=paras, total_chars=total,
    )


def _patch_raw_loader(monkeypatch, paras_a, paras_b):
    """C8 新增的 raw_loader 需要 mock(每侧返指定 raw body 段落列表)。"""
    call_count = {"n": 0}

    async def _fake_load(session, doc_id):
        call_count["n"] += 1
        return paras_a if call_count["n"] % 2 == 1 else paras_b

    monkeypatch.setattr(ss_mod.raw_loader, "load_raw_body_paragraphs", _fake_load)


def _sync_future(fn, *args):
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    try:
        fut.set_result(fn(*args))
    except Exception as e:
        fut.set_exception(e)
    return fut


# ---------- preflight ----------

@pytest.mark.asyncio
async def test_preflight_skip_no_shared_role(monkeypatch):
    monkeypatch.setattr(
        ss_mod.segmenter, "choose_shared_role",
        AsyncMock(return_value=[]),
    )
    ctx = _make_ctx()
    result = await ss_mod.preflight(ctx)
    assert result.status == "skip"
    assert result.reason == "缺少可对比文档"


@pytest.mark.asyncio
async def test_preflight_skip_too_short(monkeypatch):
    monkeypatch.setattr(
        ss_mod.segmenter, "choose_shared_role",
        AsyncMock(return_value=["technical"]),
    )
    monkeypatch.setattr(
        ss_mod.segmenter, "load_paragraphs_for_roles",
        AsyncMock(side_effect=[_seg(total=300), _seg(total=800)]),
    )
    ctx = _make_ctx()
    result = await ss_mod.preflight(ctx)
    assert result.status == "skip"
    assert result.reason == "文档过短无法对比"


@pytest.mark.asyncio
async def test_preflight_ok(monkeypatch):
    monkeypatch.setattr(
        ss_mod.segmenter, "choose_shared_role",
        AsyncMock(return_value=["technical"]),
    )
    monkeypatch.setattr(
        ss_mod.segmenter, "load_paragraphs_for_roles",
        AsyncMock(return_value=_seg(total=800)),
    )
    ctx = _make_ctx()
    result = await ss_mod.preflight(ctx)
    assert result.status == "ok"


# ---------- run: 章节切分失败走 fallback ----------

@pytest.mark.asyncio
async def test_run_fallback_when_chapters_insufficient(monkeypatch):
    """任一侧章节数 < MIN_CHAPTERS=3 → 走 fallback 整文档粒度。"""
    # segmenter 返回的 paras 全无章节标题,extract_chapters 返 []
    monkeypatch.setattr(
        ss_mod.segmenter, "choose_shared_role",
        AsyncMock(return_value=["technical"]),
    )
    monkeypatch.setattr(
        ss_mod.segmenter, "load_paragraphs_for_roles",
        AsyncMock(
            return_value=_seg(
                total=800,
                paras=["正文无章节标题" * 50, "继续正文" * 50],  # 无 PATTERN 命中
            )
        ),
    )
    # C8 raw_loader 返同样的无章节标题段落 → chapter_parser 返 []
    _patch_raw_loader(
        monkeypatch,
        ["正文无章节标题" * 50, "继续正文" * 50],
        ["正文无章节标题" * 50, "继续正文" * 50],
    )
    # tfidf stub
    from app.services.detect.agents.section_sim_impl import fallback as fb_mod

    monkeypatch.setattr(
        fb_mod.c7_tfidf, "compute_pair_similarity",
        lambda a, b, th, mx: [
            ParaPair(a_idx=0, b_idx=0, a_text="x", b_text="y", sim=0.9)
        ],
    )
    monkeypatch.setattr(
        asyncio, "get_running_loop",
        lambda: SimpleNamespace(
            run_in_executor=lambda ex, fn, *a: _sync_future(fn, *a)
        ),
    )

    llm_text = json.dumps({
        "pairs": [{"idx": 0, "judgment": "plagiarism"}],
        "overall": "降级命中", "confidence": "high",
    })
    provider = _StubProvider([(llm_text, None)])
    ctx = _make_ctx(llm_provider=provider)

    result = await ss_mod.run(ctx)
    assert result.evidence_json["algorithm"] == "tfidf_cosine_fallback_to_doc"
    assert result.evidence_json["degraded_to_doc_level"] is True
    assert "章节切分失败" in result.summary


# ---------- run: 章节切分成功 + LLM success 正常流 ----------

@pytest.mark.asyncio
async def test_run_success_chapter_level(monkeypatch):
    monkeypatch.setattr(
        ss_mod.segmenter, "choose_shared_role",
        AsyncMock(return_value=["technical"]),
    )
    # 段落足够且有章节标题
    paras = [
        "第一章 投标函", "投标内容" * 40, "保证实现" * 40,
        "第二章 技术方案", "技术措施" * 40, "施工组织" * 40,
        "第三章 商务标", "报价明细" * 40, "综合单价" * 40,
    ]
    monkeypatch.setattr(
        ss_mod.segmenter, "load_paragraphs_for_roles",
        AsyncMock(return_value=_seg(total=2000, paras=paras)),
    )
    _patch_raw_loader(monkeypatch, paras, paras)
    # scorer 的 tfidf:返 plagiarism 段对
    from app.services.detect.agents.section_sim_impl import scorer as scorer_mod

    monkeypatch.setattr(
        scorer_mod.c7_tfidf, "compute_pair_similarity",
        lambda a, b, th, mx: [
            ParaPair(a_idx=0, b_idx=0, a_text="x", b_text="y", sim=0.9)
        ],
    )
    monkeypatch.setattr(
        asyncio, "get_running_loop",
        lambda: SimpleNamespace(
            run_in_executor=lambda ex, fn, *a: _sync_future(fn, *a)
        ),
    )

    llm_text = json.dumps({
        "pairs": [{"idx": i, "judgment": "plagiarism"} for i in range(3)],
        "overall": "章节级命中", "confidence": "high",
    })
    provider = _StubProvider([(llm_text, None)])
    ctx = _make_ctx(llm_provider=provider)

    result = await ss_mod.run(ctx)
    assert result.evidence_json["algorithm"] == "tfidf_cosine_chapter_v1"
    assert result.evidence_json["degraded_to_doc_level"] is False
    assert len(result.evidence_json["chapter_pairs"]) >= 1


# ---------- run: 章节切分成功 + LLM timeout → chapter_v1 + degraded=true ----------

@pytest.mark.asyncio
async def test_run_chapter_success_but_llm_timeout(monkeypatch):
    monkeypatch.setattr(
        ss_mod.segmenter, "choose_shared_role",
        AsyncMock(return_value=["technical"]),
    )
    paras = [
        "第一章 投标函", "投标内容" * 40,
        "第二章 技术", "技术措施" * 40,
        "第三章 商务", "报价明细" * 40,
    ]
    monkeypatch.setattr(
        ss_mod.segmenter, "load_paragraphs_for_roles",
        AsyncMock(return_value=_seg(total=2000, paras=paras)),
    )
    _patch_raw_loader(monkeypatch, paras, paras)
    from app.services.detect.agents.section_sim_impl import scorer as scorer_mod

    monkeypatch.setattr(
        scorer_mod.c7_tfidf, "compute_pair_similarity",
        lambda a, b, th, mx: [
            ParaPair(a_idx=0, b_idx=0, a_text="x", b_text="y", sim=0.9)
        ],
    )
    monkeypatch.setattr(
        asyncio, "get_running_loop",
        lambda: SimpleNamespace(
            run_in_executor=lambda ex, fn, *a: _sync_future(fn, *a)
        ),
    )
    provider = _StubProvider([("", LLMError(kind="timeout", message="t"))])
    ctx = _make_ctx(llm_provider=provider)

    result = await ss_mod.run(ctx)
    # 章节级算法仍跑了,但 LLM 降级
    assert result.evidence_json["algorithm"] == "tfidf_cosine_chapter_v1"
    assert result.evidence_json["degraded_to_doc_level"] is False
    assert result.evidence_json["degraded"] is True
    assert "LLM" in result.summary or "不可用" in result.summary
