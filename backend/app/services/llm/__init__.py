"""LLM 适配层 - C1 infra-base

统一 Provider 接口 + 超时/限流结构化错误。降级策略由调用方决定。
"""

from app.services.llm.base import LLMError, LLMProvider, LLMResult, Message
from app.services.llm.factory import get_llm_provider

__all__ = ["LLMError", "LLMProvider", "LLMResult", "Message", "get_llm_provider"]
