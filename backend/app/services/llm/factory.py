"""LLM Provider 工厂 - C1 infra-base

根据 settings.llm_provider 选择实现,缓存单例。作为 FastAPI dependency 注入使用。
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.llm.base import LLMProvider
from app.services.llm.openai_compat import (
    PROVIDER_DEFAULT_BASE_URL,
    OpenAICompatProvider,
)


@lru_cache(maxsize=1)
def _build_default_provider() -> LLMProvider:
    provider = settings.llm_provider
    base_url = settings.llm_base_url or PROVIDER_DEFAULT_BASE_URL.get(provider)
    if base_url is None:
        raise ValueError(
            f"未知 LLM provider: {provider};请通过 LLM_BASE_URL 显式配置 base_url"
        )
    return OpenAICompatProvider(
        name=provider,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        base_url=base_url,
        timeout_s=settings.llm_timeout_s,
    )


def get_llm_provider() -> LLMProvider:
    """FastAPI dependency 入口。测试里可通过 app.dependency_overrides 替换。"""
    return _build_default_provider()
