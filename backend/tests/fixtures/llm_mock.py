"""LLM mock 统一入口 - C1 infra-base

CLAUDE.md 测试标准约定:所有需要 mock LLM 的测试(后续 L-1/L-2 + 7 个文本相似类 Agent,
共 8 个调用点)**必须**从此模块取 fixture,不允许各自 mock,避免行为漂移。

使用方式:
    @pytest.fixture
    def mock_llm_provider(): ...      # 默认 mock 返回 text="mocked"
    @pytest.fixture
    def mock_llm_provider_timeout(): ...  # 模拟超时错
    @pytest.fixture
    def mock_llm_provider_rate_limit(): ...  # 模拟限流错
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.services.llm.base import ErrorKind, LLMError, LLMResult, Message


@dataclass
class MockLLMProvider:
    """可编程 mock provider:按需构造成功/失败响应。

    - 默认成功:返回 LLMResult(text="mocked")
    - 失败:设置 error_kind,返回对应 LLMError
    - calls:记录调用历史,测试里可断言
    """

    name: str = "mock"
    response_text: str = "mocked"
    error_kind: ErrorKind | None = None
    error_message: str = "mocked error"
    calls: list[list[Message]] = field(default_factory=list)

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        self.calls.append(list(messages))
        if self.error_kind is not None:
            return LLMResult(
                text="",
                error=LLMError(kind=self.error_kind, message=self.error_message),
            )
        return LLMResult(text=self.response_text)


@pytest.fixture
def mock_llm_provider() -> MockLLMProvider:
    """默认成功 mock。测试里可 .error_kind = 'timeout' 等切换成失败分支。"""
    return MockLLMProvider()


@pytest.fixture
def mock_llm_provider_timeout() -> MockLLMProvider:
    return MockLLMProvider(error_kind="timeout", error_message="mocked timeout")


@pytest.fixture
def mock_llm_provider_rate_limit() -> MockLLMProvider:
    return MockLLMProvider(error_kind="rate_limit", error_message="mocked 429")
