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


# C5 新增:parser-pipeline 专用 mock 工厂 -----------------------------------


def make_role_classify_response(
    doc_roles: list[tuple[int, str]],
    identity_info: dict | None = None,
    confidence: str = "high",
) -> str:
    """构造 role_classifier LLM 成功响应 JSON 文本。"""
    import json

    return json.dumps(
        {
            "roles": [
                {"document_id": did, "role": r, "confidence": confidence}
                for did, r in doc_roles
            ],
            "identity_info": identity_info or {},
        }
    )


def make_price_rule_response(
    sheet_name: str = "报价清单",
    header_row: int = 2,
    mapping: dict | None = None,
) -> str:
    """构造 price_rule_detector LLM 成功响应 JSON 文本。"""
    import json

    default_mapping = {
        "code_col": "A",
        "name_col": "B",
        "unit_col": "C",
        "qty_col": "D",
        "unit_price_col": "E",
        "total_price_col": "F",
        "skip_cols": [],
    }
    return json.dumps(
        {
            "sheet_name": sheet_name,
            "header_row": header_row,
            "column_mapping": mapping or default_mapping,
        }
    )


class ScriptedLLMProvider:
    """按调用顺序依次返不同响应/错 的 provider。用于 rule_coordinator 等多次调用场景。"""

    def __init__(self, scripts: list, *, loop_last: bool = True):
        self.name = "scripted"
        self._scripts = list(scripts)
        self._loop_last = loop_last
        self._cursor = 0
        self.calls: list[list[Message]] = []

    async def complete(
        self, messages: list[Message], **kwargs
    ) -> LLMResult:
        self.calls.append(list(messages))
        if self._cursor >= len(self._scripts):
            if not self._loop_last:
                return LLMResult(
                    text="",
                    error=LLMError(kind="other", message="exhausted"),
                )
            item = self._scripts[-1]
        else:
            item = self._scripts[self._cursor]
            self._cursor += 1
        if isinstance(item, str):
            return LLMResult(text=item)
        if isinstance(item, LLMError):
            return LLMResult(text="", error=item)
        return LLMResult(text="", error=LLMError(kind=item, message="mock"))
