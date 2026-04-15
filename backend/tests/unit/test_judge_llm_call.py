"""L1 - judge_llm.call_llm_judge (C14)"""

from __future__ import annotations

import json

import pytest

from app.services.detect.judge_llm import LLMJudgeConfig, call_llm_judge


# 本模块内本地辅助(不污染生产模块)— 避免循环 import fixture
def _l9_response(
    suggested_total: float = 78.0,
    conclusion: str = "综合研判:中等围标嫌疑。",
    reasoning: str = "mock",
) -> str:
    return json.dumps(
        {
            "suggested_total": suggested_total,
            "conclusion": conclusion,
            "reasoning": reasoning,
        },
        ensure_ascii=False,
    )


class _Provider:
    """最小 provider 实现(不走 ScriptedLLMProvider 以独立单元测试)"""

    name = "test"

    def __init__(self, scripts: list):
        self._scripts = list(scripts)
        self._cursor = 0
        self.calls = 0

    async def complete(self, messages, *, temperature=0.0, max_tokens=None):
        from app.services.llm.base import LLMError, LLMResult

        self.calls += 1
        if self._cursor >= len(self._scripts):
            item = self._scripts[-1]  # loop_last
        else:
            item = self._scripts[self._cursor]
            self._cursor += 1
        if isinstance(item, str):
            return LLMResult(text=item)
        if isinstance(item, LLMError):
            return LLMResult(text="", error=item)
        raise ValueError(f"bad script item: {item!r}")


_CFG = LLMJudgeConfig(max_retry=2)


@pytest.mark.asyncio
async def test_first_attempt_ok():
    provider = _Provider([_l9_response(suggested_total=78.0)])
    conclusion, suggested = await call_llm_judge(
        {}, 50.0, provider=provider, cfg=_CFG
    )
    assert provider.calls == 1
    assert suggested == 78.0
    assert conclusion.startswith("综合研判")


@pytest.mark.asyncio
async def test_bad_json_consumes_retry_then_success():
    provider = _Provider(
        ["not json", _l9_response(suggested_total=80.0)]
    )
    conclusion, suggested = await call_llm_judge(
        {}, 50.0, provider=provider, cfg=_CFG
    )
    assert provider.calls == 2
    assert suggested == 80.0


@pytest.mark.asyncio
async def test_retry_exhausted_returns_none():
    """3 次全 bad JSON → (None, None)"""
    provider = _Provider(["not json", "not json", "not json"])
    conclusion, suggested = await call_llm_judge(
        {}, 50.0, provider=provider, cfg=LLMJudgeConfig(max_retry=2)
    )
    assert provider.calls == 3  # MAX_RETRY+1
    assert conclusion is None and suggested is None


@pytest.mark.asyncio
async def test_suggested_total_out_of_range_consumes_retry():
    """suggested 超界 → 视为失败消费重试"""
    provider = _Provider(
        [
            _l9_response(suggested_total=150.0),  # 超界
            _l9_response(suggested_total=-10.0),  # 超界
            _l9_response(suggested_total=75.0),  # 合法
        ]
    )
    conclusion, suggested = await call_llm_judge(
        {}, 50.0, provider=provider, cfg=LLMJudgeConfig(max_retry=2)
    )
    assert provider.calls == 3
    assert suggested == 75.0


@pytest.mark.asyncio
async def test_empty_conclusion_consumes_retry():
    """conclusion 空串 → 失败"""
    provider = _Provider(
        [_l9_response(conclusion=""), _l9_response(conclusion="有效")]
    )
    conclusion, suggested = await call_llm_judge(
        {}, 50.0, provider=provider, cfg=_CFG
    )
    assert provider.calls == 2
    assert conclusion == "有效"


@pytest.mark.asyncio
async def test_missing_field_consumes_retry():
    """缺必填字段 → 失败"""
    provider = _Provider(
        [
            json.dumps({"conclusion": "foo"}),  # 缺 suggested_total
            json.dumps({"suggested_total": 75}),  # 缺 conclusion
            _l9_response(),
        ]
    )
    conclusion, suggested = await call_llm_judge(
        {}, 50.0, provider=provider, cfg=LLMJudgeConfig(max_retry=2)
    )
    assert provider.calls == 3
    assert conclusion is not None


@pytest.mark.asyncio
async def test_timeout_error_returns_none():
    from app.services.llm.base import LLMError

    provider = _Provider(
        [
            LLMError(kind="timeout", message="mock"),
            LLMError(kind="timeout", message="mock"),
            LLMError(kind="timeout", message="mock"),
        ]
    )
    conclusion, suggested = await call_llm_judge(
        {}, 50.0, provider=provider, cfg=LLMJudgeConfig(max_retry=2)
    )
    assert provider.calls == 3
    assert conclusion is None


@pytest.mark.asyncio
async def test_fallback_prefix_in_conclusion_rejected():
    """LLM 违反约束返回以降级前缀开头的 conclusion → 视为失败"""
    provider = _Provider(
        [_l9_response(conclusion="AI 综合研判暂不可用,balabala")]
    )
    conclusion, suggested = await call_llm_judge(
        {}, 50.0, provider=provider, cfg=LLMJudgeConfig(max_retry=0)
    )
    assert conclusion is None


@pytest.mark.asyncio
async def test_provider_none_returns_none():
    conclusion, suggested = await call_llm_judge(
        {}, 50.0, provider=None, cfg=_CFG
    )
    assert conclusion is None and suggested is None
