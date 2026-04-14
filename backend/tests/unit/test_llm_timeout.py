"""L1: LLM 适配层超时 → 结构化 error,不抛异常(降级由调用方决定)"""

from __future__ import annotations

import pytest

from app.services.llm.base import LLMResult
from tests.fixtures.llm_mock import MockLLMProvider


@pytest.mark.asyncio
async def test_llm_timeout_returns_structured_error(
    mock_llm_provider_timeout: MockLLMProvider,
) -> None:
    result: LLMResult = await mock_llm_provider_timeout.complete(
        [{"role": "user", "content": "slow"}]
    )
    # 契约:永远不抛异常,失败时 error != None,调用方决定降级
    assert not result.ok
    assert result.error is not None
    assert result.error.kind == "timeout"
    assert result.text == ""


@pytest.mark.asyncio
async def test_llm_rate_limit_returns_structured_error(
    mock_llm_provider_rate_limit: MockLLMProvider,
) -> None:
    result: LLMResult = await mock_llm_provider_rate_limit.complete(
        [{"role": "user", "content": "hi"}]
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.kind == "rate_limit"
