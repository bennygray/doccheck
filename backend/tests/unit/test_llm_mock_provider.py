"""L1: LLM mock provider 走通统一接口(默认返回成功)"""

from __future__ import annotations

import pytest

from app.services.llm.base import LLMProvider, LLMResult
from tests.fixtures.llm_mock import MockLLMProvider


@pytest.mark.asyncio
async def test_mock_llm_provider_default_ok(mock_llm_provider: MockLLMProvider) -> None:
    # MockLLMProvider 满足 LLMProvider Protocol(runtime_checkable)
    assert isinstance(mock_llm_provider, LLMProvider)

    result = await mock_llm_provider.complete(
        [{"role": "user", "content": "hi"}]
    )
    assert isinstance(result, LLMResult)
    assert result.ok
    assert result.text == "mocked"
    assert result.error is None

    # 记录了调用
    assert len(mock_llm_provider.calls) == 1
    assert mock_llm_provider.calls[0] == [{"role": "user", "content": "hi"}]
