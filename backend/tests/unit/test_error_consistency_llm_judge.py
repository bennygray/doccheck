"""L1 - error_impl/llm_judge (C13 L-5 LLM)"""

from __future__ import annotations

import pytest

from app.services.detect.agents.error_impl.config import (
    ErrorConsistencyConfig,
)
from app.services.detect.agents.error_impl.llm_judge import (
    _parse_response,
    call_l5,
)
from app.services.detect.agents.error_impl.models import SuspiciousSegment
from app.services.llm.base import LLMError, LLMResult


class _MockProvider:
    """简单 mock provider:可控制返回 LLMResult 序列。"""

    def __init__(self, results: list[LLMResult]):
        self.name = "mock"
        self._results = list(results)
        self._cursor = 0

    async def complete(self, messages, **kwargs):
        if self._cursor < len(self._results):
            r = self._results[self._cursor]
            self._cursor += 1
            return r
        return self._results[-1]


def _seg(pid: int = 1) -> SuspiciousSegment:
    return SuspiciousSegment(
        paragraph_text=f"段落{pid}",
        doc_id=pid,
        doc_role="technical",
        position="body",
        matched_keywords=["张三"],
        source_bidder_id=1,
    )


@pytest.mark.asyncio
async def test_iron_evidence_response() -> None:
    cfg = ErrorConsistencyConfig(llm_max_retries=0)
    provider = _MockProvider(
        [
            LLMResult(
                text='{"is_cross_contamination":true,"direct_evidence":true,'
                '"confidence":0.9,"evidence":[]}'
            )
        ]
    )
    judgment = await call_l5(provider, [_seg()], "甲", "乙", cfg)
    assert judgment is not None
    assert judgment["direct_evidence"] is True
    assert judgment["is_cross_contamination"] is True


@pytest.mark.asyncio
async def test_non_iron_response() -> None:
    cfg = ErrorConsistencyConfig(llm_max_retries=0)
    provider = _MockProvider(
        [
            LLMResult(
                text='{"is_cross_contamination":true,"direct_evidence":false,'
                '"confidence":0.5,"evidence":[]}'
            )
        ]
    )
    judgment = await call_l5(provider, [_seg()], "甲", "乙", cfg)
    assert judgment["direct_evidence"] is False


@pytest.mark.asyncio
async def test_provider_none_returns_none() -> None:
    cfg = ErrorConsistencyConfig(llm_max_retries=0)
    judgment = await call_l5(None, [_seg()], "甲", "乙", cfg)
    assert judgment is None


@pytest.mark.asyncio
async def test_empty_segments_returns_none() -> None:
    cfg = ErrorConsistencyConfig(llm_max_retries=0)
    provider = _MockProvider([LLMResult(text='{}')])
    judgment = await call_l5(provider, [], "甲", "乙", cfg)
    assert judgment is None


@pytest.mark.asyncio
async def test_llm_error_returns_none_after_retries() -> None:
    cfg = ErrorConsistencyConfig(llm_max_retries=2)
    provider = _MockProvider(
        [LLMResult(text="", error=LLMError(kind="timeout", message="x"))] * 3
    )
    judgment = await call_l5(provider, [_seg()], "甲", "乙", cfg)
    assert judgment is None


@pytest.mark.asyncio
async def test_bad_json_returns_none() -> None:
    cfg = ErrorConsistencyConfig(llm_max_retries=0)
    provider = _MockProvider([LLMResult(text="not json at all")])
    judgment = await call_l5(provider, [_seg()], "甲", "乙", cfg)
    assert judgment is None


@pytest.mark.asyncio
async def test_retry_succeeds_after_first_fail() -> None:
    cfg = ErrorConsistencyConfig(llm_max_retries=2)
    provider = _MockProvider(
        [
            LLMResult(text="bad json"),
            LLMResult(
                text='{"is_cross_contamination":true,"direct_evidence":true,'
                '"confidence":0.8,"evidence":[]}'
            ),
        ]
    )
    judgment = await call_l5(provider, [_seg()], "甲", "乙", cfg)
    assert judgment is not None
    assert judgment["direct_evidence"] is True


def test_parse_markdown_wrapped_json() -> None:
    """容错 ```json ... ``` 包装。"""
    s = '```json\n{"is_cross_contamination":true,"direct_evidence":false,"confidence":0.7}\n```'
    result = _parse_response(s)
    assert result is not None
    assert result["is_cross_contamination"] is True


def test_parse_empty_returns_none() -> None:
    assert _parse_response("") is None
    assert _parse_response("   ") is None
