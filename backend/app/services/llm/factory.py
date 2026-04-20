"""LLM Provider 工厂 - C1 infra-base + admin-llm-config

原始设计(C1):@lru_cache 读 env settings 单例,运行期不可变。
admin-llm-config 扩展:
  - 支持从 DB(SystemConfig.config.llm)动态读取
  - 按配置指纹哈希缓存 Provider(多配置共存)
  - PUT /api/admin/llm 成功后调 invalidate_provider_cache() 清空

向后兼容:
  - 不传 session → 回退 env 路径(保持 11 Agent / judge / pipeline 的老调用)
  - 传 session → 走 DB 三层 fallback(DB > env > 默认)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import settings
from app.services.llm.base import LLMProvider
from app.services.llm.openai_compat import (
    PROVIDER_DEFAULT_BASE_URL,
    OpenAICompatProvider,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# 指纹 → Provider 缓存。指纹 = (provider, api_key, model, base_url, timeout)
_ProviderKey = tuple[str, str, str, str | None, int]
_providers: dict[_ProviderKey, LLMProvider] = {}

# 缓存上限,防止病态输入撑爆(admin 改 key 偶发,不会触发)
_MAX_CACHE_ENTRIES = 3


def _build_provider(
    provider: str,
    api_key: str,
    model: str,
    base_url: str | None,
    timeout_s: float,
) -> LLMProvider:
    """按配置构造 Provider(不访问缓存)。"""
    resolved_base = base_url or PROVIDER_DEFAULT_BASE_URL.get(provider)
    if resolved_base is None:
        raise ValueError(
            f"未知 LLM provider: {provider};请通过 base_url 显式配置"
        )
    return OpenAICompatProvider(
        name=provider,
        api_key=api_key,
        model=model,
        base_url=resolved_base,
        timeout_s=timeout_s,
    )


def _get_or_create(key: _ProviderKey) -> LLMProvider:
    """按 key 命中或新建 Provider;自动淘汰最老条目。"""
    cached = _providers.get(key)
    if cached is not None:
        return cached
    if len(_providers) >= _MAX_CACHE_ENTRIES:
        # FIFO 淘汰最先插入的一个(dict 保持插入序)
        oldest_key = next(iter(_providers))
        _providers.pop(oldest_key, None)
    provider_obj = _build_provider(
        provider=key[0],
        api_key=key[1],
        model=key[2],
        base_url=key[3],
        timeout_s=float(key[4]),
    )
    _providers[key] = provider_obj
    return provider_obj


def get_llm_provider(session: "AsyncSession | None" = None) -> LLMProvider:
    """FastAPI dependency 入口。

    向后兼容:不传 session → env 路径(同步场景 / 旧调用);
    传 session → 走 DB 三层 fallback。

    注:session 是同步签名但内部调用 await,故本函数保持同步返回,不读 DB;
    需要 DB 路径的调用方用 get_llm_provider_db(session)。
    """
    # 同步路径 = env 直读(C1 行为)
    base_url = settings.llm_base_url or PROVIDER_DEFAULT_BASE_URL.get(
        settings.llm_provider
    )
    if base_url is None:
        raise ValueError(
            f"未知 LLM provider: {settings.llm_provider};"
            f"请通过 LLM_BASE_URL 显式配置 base_url"
        )
    key: _ProviderKey = (
        settings.llm_provider,
        settings.llm_api_key,
        settings.llm_model,
        base_url,
        int(settings.llm_timeout_s),
    )
    return _get_or_create(key)


async def get_llm_provider_db(session: "AsyncSession") -> LLMProvider:
    """异步路径:按 DB > env > 默认三层 fallback 读配置建 Provider。

    admin-llm-config 新增 API,检测 Agent 和 judge 后续可逐步切换到此函数。
    """
    from app.services.admin.llm_reader import read_llm_config

    cfg = await read_llm_config(session)
    resolved_base = cfg.base_url or PROVIDER_DEFAULT_BASE_URL.get(cfg.provider)
    if resolved_base is None:
        raise ValueError(
            f"未知 LLM provider: {cfg.provider};请通过 base_url 显式配置"
        )
    key: _ProviderKey = (
        cfg.provider,
        cfg.api_key,
        cfg.model,
        resolved_base,
        cfg.timeout_s,
    )
    return _get_or_create(key)


def invalidate_provider_cache() -> None:
    """PUT /api/admin/llm 后调;清空指纹缓存,下次调用重建。"""
    _providers.clear()
