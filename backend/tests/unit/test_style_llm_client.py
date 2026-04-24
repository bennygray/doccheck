"""L1 - style_impl/llm_client (C13 L-8 两阶段)"""

from __future__ import annotations

import pytest

from app.services.detect.agents.style_impl import llm_client
from app.services.detect.agents.style_impl.config import StyleConfig
from app.services.detect.agents.style_impl.models import StyleFeatureBrief
from app.services.llm.base import LLMError, LLMResult


class _MockProvider:
    def __init__(self, results):
        self.name = "mock"
        self._results = list(results)
        self._cursor = 0

    async def complete(self, messages, **kwargs):
        if self._cursor < len(self._results):
            r = self._results[self._cursor]
            self._cursor += 1
            return r
        return self._results[-1]


@pytest.mark.asyncio
async def test_stage1_success() -> None:
    cfg = StyleConfig(llm_max_retries=0)
    provider = _MockProvider(
        [
            LLMResult(
                text='{"用词偏好":"口语","句式特点":"短句","标点习惯":"顿号","段落组织":"总分总"}'
            )
        ]
    )
    brief = await llm_client.call_l8_stage1(
        provider, 1, ["段落内容"], cfg
    )
    assert brief is not None
    assert brief["用词偏好"] == "口语"


@pytest.mark.asyncio
async def test_stage2_success() -> None:
    cfg = StyleConfig(llm_max_retries=0)
    provider = _MockProvider(
        [
            LLMResult(
                text='{"consistent_groups":[{"bidder_ids":[1,2],"consistency_score":0.9,"typical_features":"共同特征"}]}'
            )
        ]
    )
    briefs = {
        1: StyleFeatureBrief(bidder_id=1),
        2: StyleFeatureBrief(bidder_id=2),
    }
    comp = await llm_client.call_l8_stage2(provider, briefs, cfg)
    assert comp is not None
    assert len(comp["consistent_groups"]) == 1


@pytest.mark.asyncio
async def test_stage1_llm_timeout_raises_skipped() -> None:
    """harden-async-infra N7:所有重试耗尽 → 抛 AgentSkippedError(LLM 超时)。"""
    from app.services.detect.errors import (
        SKIP_REASON_LLM_TIMEOUT,
        AgentSkippedError,
    )

    cfg = StyleConfig(llm_max_retries=2)
    provider = _MockProvider(
        [LLMResult(text="", error=LLMError(kind="timeout", message="x"))] * 3
    )
    with pytest.raises(AgentSkippedError) as excinfo:
        await llm_client.call_l8_stage1(provider, 1, ["p"], cfg)
    assert str(excinfo.value) == SKIP_REASON_LLM_TIMEOUT


@pytest.mark.asyncio
async def test_stage2_llm_rate_limit_raises_skipped() -> None:
    """不同 error.kind 映射到不同的 skip reason。"""
    from app.services.detect.errors import (
        SKIP_REASON_LLM_RATE_LIMIT,
        AgentSkippedError,
    )

    cfg = StyleConfig(llm_max_retries=1)
    provider = _MockProvider(
        [LLMResult(text="", error=LLMError(kind="rate_limit", message="x"))] * 3
    )
    briefs = {1: StyleFeatureBrief(bidder_id=1)}
    with pytest.raises(AgentSkippedError) as excinfo:
        await llm_client.call_l8_stage2(provider, briefs, cfg)
    assert str(excinfo.value) == SKIP_REASON_LLM_RATE_LIMIT


@pytest.mark.asyncio
async def test_stage1_bad_json_raises_skipped() -> None:
    """解析失败也会耗尽重试 → 抛 AgentSkippedError(LLM 返回异常)。"""
    from app.services.detect.errors import (
        SKIP_REASON_LLM_BAD_RESPONSE,
        AgentSkippedError,
    )

    cfg = StyleConfig(llm_max_retries=0)
    provider = _MockProvider([LLMResult(text="not json")])
    with pytest.raises(AgentSkippedError) as excinfo:
        await llm_client.call_l8_stage1(provider, 1, ["p"], cfg)
    assert str(excinfo.value) == SKIP_REASON_LLM_BAD_RESPONSE


@pytest.mark.asyncio
async def test_stage1_provider_none_returns_none() -> None:
    cfg = StyleConfig(llm_max_retries=0)
    result = await llm_client.call_l8_stage1(None, 1, ["p"], cfg)
    assert result is None


@pytest.mark.asyncio
async def test_stage2_empty_briefs_returns_none() -> None:
    cfg = StyleConfig(llm_max_retries=0)
    provider = _MockProvider([LLMResult(text="{}")])
    result = await llm_client.call_l8_stage2(provider, {}, cfg)
    assert result is None


@pytest.mark.asyncio
async def test_stage1_retry_succeeds() -> None:
    cfg = StyleConfig(llm_max_retries=2)
    provider = _MockProvider(
        [
            LLMResult(text="bad json"),
            LLMResult(
                text='{"用词偏好":"x","句式特点":"y","标点习惯":"z","段落组织":"w"}'
            ),
        ]
    )
    brief = await llm_client.call_l8_stage1(provider, 1, ["p"], cfg)
    assert brief is not None
