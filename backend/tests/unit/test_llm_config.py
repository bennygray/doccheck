"""L1 admin-llm-config 单元测试

覆盖:
- mask_api_key 三种输入(长/短/空)
- LLMConfigUpdate 校验(非法 provider、非法 base_url、timeout 越界)
"""

from __future__ import annotations

import pytest

from app.schemas.admin import LLMConfigUpdate
from app.services.admin.llm_reader import mask_api_key


def test_mask_api_key_long():
    assert mask_api_key("sk-abcdef1234567890") == "sk-****7890"


def test_mask_api_key_short():
    assert mask_api_key("abc") == "sk-****"


def test_mask_api_key_empty():
    assert mask_api_key("") == ""
    assert mask_api_key(None) == ""


def test_mask_api_key_exactly_8():
    # 恰好 8 字符 → 正常脱敏
    assert mask_api_key("abcdefgh") == "abc****efgh"


def test_update_schema_valid_provider():
    body = LLMConfigUpdate(
        provider="dashscope",
        api_key="sk-xyz",
        model="qwen-plus",
        timeout_s=30,
    )
    assert body.provider == "dashscope"
    assert body.timeout_s == 30


def test_update_schema_invalid_provider():
    with pytest.raises(ValueError):
        LLMConfigUpdate(
            provider="unknown",
            model="gpt-4",
            timeout_s=30,
        )


def test_update_schema_invalid_base_url():
    with pytest.raises(ValueError):
        LLMConfigUpdate(
            provider="custom",
            model="gpt-4",
            base_url="not-a-url",
            timeout_s=30,
        )


def test_update_schema_base_url_trim_slash():
    body = LLMConfigUpdate(
        provider="custom",
        model="gpt-4",
        base_url="https://api.example.com/v1/",
        timeout_s=30,
    )
    assert body.base_url == "https://api.example.com/v1"


def test_update_schema_timeout_out_of_range():
    with pytest.raises(ValueError):
        LLMConfigUpdate(provider="openai", model="gpt-4", timeout_s=500)
    with pytest.raises(ValueError):
        LLMConfigUpdate(provider="openai", model="gpt-4", timeout_s=0)


def test_update_schema_empty_base_url_becomes_none():
    body = LLMConfigUpdate(
        provider="dashscope", model="qwen-plus", base_url="", timeout_s=30
    )
    assert body.base_url is None


def test_update_schema_api_key_optional():
    # 不传 api_key(保持旧值)
    body = LLMConfigUpdate(provider="dashscope", model="qwen-plus", timeout_s=30)
    assert body.api_key is None
