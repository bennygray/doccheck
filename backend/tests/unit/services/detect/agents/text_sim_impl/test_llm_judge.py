"""L1 - text_sim_impl.llm_judge 单元测试 (C7)"""

from __future__ import annotations

import json

import pytest

from app.services.detect.agents.text_sim_impl.llm_judge import (
    build_prompt,
    call_llm_judge,
    parse_response,
)
from app.services.detect.agents.text_sim_impl.models import ParaPair
from app.services.llm.base import LLMError, LLMResult


class _StubProvider:
    name = "stub"

    def __init__(self, responses):
        # responses: list of (text, error_or_None) tuples; loops last
        self._responses = list(responses)
        self.calls = 0

    async def complete(self, messages, **kwargs):
        self.calls += 1
        item = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        text, err = item
        return LLMResult(text=text or "", error=err)


def _pair(idx: int) -> ParaPair:
    return ParaPair(a_idx=idx, b_idx=idx, a_text=f"a{idx}", b_text=f"b{idx}", sim=0.9)


# ---------- build_prompt ----------

def test_build_prompt_contains_all_fields():
    pairs = [_pair(0), _pair(1)]
    msgs = build_prompt("甲公司", "乙公司", "technical", pairs)
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    content = msgs[1]["content"]
    assert "甲公司" in content and "乙公司" in content
    assert "technical" in content
    # 段落 JSON 载荷
    assert '"idx": 0' in content and '"idx": 1' in content


# ---------- parse_response ----------

def test_parse_response_valid_json():
    text = json.dumps({
        "pairs": [
            {"idx": 0, "judgment": "plagiarism", "note": "x"},
            {"idx": 1, "judgment": "generic", "note": "y"},
        ],
        "overall": "ok",
        "confidence": "high",
    })
    result = parse_response(text, 2)
    assert result is not None
    judgments, meta = result
    assert judgments == {0: "plagiarism", 1: "generic"}
    assert meta["confidence"] == "high"


def test_parse_response_markdown_fence():
    inner = {
        "pairs": [{"idx": 0, "judgment": "template"}],
        "overall": "x",
        "confidence": "low",
    }
    text = f"```json\n{json.dumps(inner)}\n```"
    result = parse_response(text, 1)
    assert result is not None
    judgments, _ = result
    assert judgments == {0: "template"}


def test_parse_response_missing_idx_fills_generic():
    text = json.dumps({
        "pairs": [{"idx": 0, "judgment": "plagiarism"}],  # 只返 1 对,输入 3 对
        "overall": "", "confidence": "",
    })
    result = parse_response(text, 3)
    assert result is not None
    judgments, _ = result
    assert judgments == {0: "plagiarism", 1: "generic", 2: "generic"}


def test_parse_response_invalid_judgment_filtered():
    text = json.dumps({
        "pairs": [{"idx": 0, "judgment": "xxx_invalid"}],  # 非法 → 漏返补 generic
        "overall": "", "confidence": "",
    })
    result = parse_response(text, 1)
    assert result is not None
    judgments, _ = result
    assert judgments == {0: "generic"}


def test_parse_response_not_json_returns_none():
    assert parse_response("this is not json", 3) is None
    assert parse_response("", 1) is None


def test_parse_response_missing_pairs_key_returns_none():
    text = json.dumps({"overall": "x", "confidence": "y"})
    assert parse_response(text, 1) is None


# ---------- call_llm_judge ----------

@pytest.mark.asyncio
async def test_call_llm_judge_none_provider_degrades():
    judgments, meta = await call_llm_judge(None, "A", "B", "tech", [_pair(0)])
    assert judgments == {} and meta is None


@pytest.mark.asyncio
async def test_call_llm_judge_empty_pairs_degrades_quickly():
    provider = _StubProvider([("{}", None)])
    judgments, meta = await call_llm_judge(provider, "A", "B", "tech", [])
    assert judgments == {} and meta is None
    # 空 pairs 不应调 provider
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_call_llm_judge_success_first_try():
    text = json.dumps({
        "pairs": [{"idx": 0, "judgment": "plagiarism"}],
        "overall": "抄袭", "confidence": "high",
    })
    provider = _StubProvider([(text, None)])
    judgments, meta = await call_llm_judge(provider, "A", "B", "tech", [_pair(0)])
    assert judgments == {0: "plagiarism"}
    assert meta["confidence"] == "high"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_call_llm_judge_bad_json_retries_then_degrades():
    provider = _StubProvider([
        ("not json", None),
        ("still not json", None),
    ])
    judgments, meta = await call_llm_judge(provider, "A", "B", "tech", [_pair(0)])
    assert judgments == {} and meta is None
    assert provider.calls == 2  # 初次 + 重试


@pytest.mark.asyncio
async def test_call_llm_judge_timeout_immediate_degrade():
    provider = _StubProvider([
        ("", LLMError(kind="timeout", message="t")),
    ])
    judgments, meta = await call_llm_judge(provider, "A", "B", "tech", [_pair(0)])
    assert judgments == {} and meta is None
    assert provider.calls == 1  # timeout 不重试


@pytest.mark.asyncio
async def test_call_llm_judge_bad_response_retries():
    """bad_response 错类允许 1 次重试。"""
    provider = _StubProvider([
        ("", LLMError(kind="bad_response", message="b")),
        ("", LLMError(kind="bad_response", message="b")),
    ])
    judgments, meta = await call_llm_judge(provider, "A", "B", "tech", [_pair(0)])
    assert judgments == {} and meta is None
    assert provider.calls == 2
