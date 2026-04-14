"""LLM 适配层基础类型 - C1 infra-base

设计要点:
- LLMProvider 是 Protocol,任意实现(真实/mock)都可注入
- complete() 永远不抛异常;超时/限流/格式错都返回 LLMResult(error=LLMError(...))
- 降级策略由调用方决定(规则兜底/本地算法/跳过)— 适配层**不**内置自动 fallback
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, TypedDict, runtime_checkable


class Message(TypedDict):
    """OpenAI-compatible chat message"""

    role: Literal["system", "user", "assistant"]
    content: str


ErrorKind = Literal["timeout", "rate_limit", "auth", "network", "bad_response", "other"]


@dataclass(frozen=True)
class LLMError:
    kind: ErrorKind
    message: str
    status_code: int | None = None


@dataclass(frozen=True)
class LLMResult:
    """LLM 调用结果。成功时 error is None,失败时 text 可能为空字符串。"""

    text: str
    error: LLMError | None = None
    raw: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None


@runtime_checkable
class LLMProvider(Protocol):
    """统一 Provider 接口。所有实现(真实/mock)都必须遵守。"""

    name: str

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        """调用 LLM。永远不抛异常;失败时 LLMResult.error != None。"""
        ...
