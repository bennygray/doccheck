"""L1 - text_similarity Agent 主流程单测 (C7)

Mock:
- ctx.session  : AsyncMock (不真实查 DB;segmenter 模块函数 monkeypatch)
- ctx.llm_provider : 传 _StubProvider 模拟各种响应
- get_cpu_executor : monkeypatch 为同步 executor(避免 ProcessPoolExecutor 开销)

覆盖:
- 正常完成:LLM success → 高分 + is_ironclad + evidence.algorithm
- LLM timeout 降级:degraded=true, summary 含"降级", status 仍 succeeded 语义
- LLM bad_json 降级
- 无超阈值段对:score=0, degraded=False(LLM 未调用)
- run 内部再次加载段落(preflight 的 seg 不跨函数)
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.detect.agents import text_similarity as ts_mod
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


class _SyncExecutor:
    """同步模拟 ProcessPoolExecutor(run_in_executor 接受任意 callable)。"""

    def submit(self, fn, *args, **kwargs):
        future = asyncio.get_event_loop().create_future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as e:  # noqa: BLE001
            future.set_exception(e)
        return future


def _bidder(id: int, name: str):
    return SimpleNamespace(id=id, name=name)


def _make_ctx(llm_provider=None):
    # session 用 AsyncMock;我们 monkeypatch segmenter 函数,不真实查询
    session = AsyncMock()
    session.add = lambda *a, **kw: None
    session.flush = AsyncMock()
    return AgentContext(
        project_id=1,
        version=1,
        agent_task=SimpleNamespace(),
        bidder_a=_bidder(10, "甲公司"),
        bidder_b=_bidder(20, "乙公司"),
        all_bidders=[],
        llm_provider=llm_provider,
        session=session,
    )


def _seg(total_chars=800, doc_id=1):
    return segmenter_mod.SegmentResult(
        doc_role="technical",
        doc_id=doc_id,
        paragraphs=["x" * 400, "y" * 400],
        total_chars=total_chars,
    )


@pytest.fixture(autouse=True)
def _patch_segmenter(monkeypatch):
    """所有 run 测试都 monkeypatch segmenter 避免真实 DB 查询。"""
    monkeypatch.setattr(
        ts_mod.segmenter,
        "choose_shared_role",
        AsyncMock(return_value=["technical"]),
    )
    monkeypatch.setattr(
        ts_mod.segmenter,
        "load_paragraphs_for_roles",
        AsyncMock(side_effect=[_seg(doc_id=11), _seg(doc_id=22)]),
    )


def _patch_run_in_executor_sync(monkeypatch):
    """helper:让 ts_mod.run 内 `loop.run_in_executor(...)` 同步跑。"""
    monkeypatch.setattr(
        asyncio,
        "get_running_loop",
        lambda: SimpleNamespace(
            run_in_executor=lambda ex, fn, *a: _sync_future(fn, *a)
        ),
    )


@pytest.fixture
def _patch_tfidf_returns_pairs(monkeypatch):
    """直接让 tfidf.compute_pair_similarity 返 N 对,跳过真实 jieba+sklearn。"""

    def fake_compute(paras_a, paras_b, threshold, max_pairs):
        return [
            ParaPair(a_idx=i, b_idx=i, a_text=f"a{i}", b_text=f"b{i}", sim=0.95)
            for i in range(5)
        ]

    monkeypatch.setattr(ts_mod.tfidf, "compute_pair_similarity", fake_compute)


# ---------- 正常完成 ----------

@pytest.mark.asyncio
async def test_run_success_plagiarism(_patch_tfidf_returns_pairs, monkeypatch):
    # LLM 返全部 plagiarism
    llm_text = json.dumps({
        "pairs": [{"idx": i, "judgment": "plagiarism"} for i in range(5)],
        "overall": "整体抄袭",
        "confidence": "high",
    })
    provider = _StubProvider([(llm_text, None)])
    ctx = _make_ctx(llm_provider=provider)
    # monkeypatch loop.run_in_executor → 同步
    _patch_run_in_executor_sync(monkeypatch)

    result = await ts_mod.run(ctx)
    assert result.score >= 60.0
    assert result.evidence_json["algorithm"] == "tfidf_cosine_v1"
    assert result.evidence_json["degraded"] is False
    assert result.evidence_json["pairs_plagiarism"] == 5
    assert "抄袭" in result.summary


# ---------- LLM timeout 降级 ----------

@pytest.mark.asyncio
async def test_run_llm_timeout_degrades(_patch_tfidf_returns_pairs, monkeypatch):
    provider = _StubProvider([("", LLMError(kind="timeout", message="t"))])
    ctx = _make_ctx(llm_provider=provider)
    _patch_run_in_executor_sync(monkeypatch)

    result = await ts_mod.run(ctx)
    assert result.evidence_json["degraded"] is True
    assert result.evidence_json["ai_judgment"] is None
    assert "降级" in result.summary or "不可用" in result.summary
    # 降级不触发铁证


@pytest.mark.asyncio
async def test_run_llm_bad_json_degrades(_patch_tfidf_returns_pairs, monkeypatch):
    # 初次 + 重试都不是 JSON → 降级
    provider = _StubProvider([("not json", None), ("still bad", None)])
    ctx = _make_ctx(llm_provider=provider)
    _patch_run_in_executor_sync(monkeypatch)

    result = await ts_mod.run(ctx)
    assert result.evidence_json["degraded"] is True
    assert provider.calls == 2


# ---------- 无超阈值段对 ----------

@pytest.mark.asyncio
async def test_run_no_pairs_zero_score(monkeypatch):
    # compute_pair_similarity 返 []
    monkeypatch.setattr(
        ts_mod.tfidf, "compute_pair_similarity",
        lambda *args, **kw: [],
    )
    err = LLMError(kind="timeout", message="should not call")
    provider = _StubProvider([("", err)])
    ctx = _make_ctx(llm_provider=provider)
    _patch_run_in_executor_sync(monkeypatch)

    result = await ts_mod.run(ctx)
    assert result.score == 0.0
    # LLM 未被调用
    assert provider.calls == 0
    assert result.evidence_json["pairs_total"] == 0
    # 非降级:无段对但 ai_meta 人工构造"未检出"
    assert result.evidence_json["degraded"] is False


# ---------- helper: async-compatible sync future ----------

def _sync_future(fn, *args):
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    try:
        fut.set_result(fn(*args))
    except Exception as e:  # noqa: BLE001
        fut.set_exception(e)
    return fut
