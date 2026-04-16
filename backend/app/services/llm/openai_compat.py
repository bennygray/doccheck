"""OpenAI-compatible LLM Provider - C1 infra-base

dashscope 与 openai 都支持 OpenAI-compatible `/v1/chat/completions` 协议,
仅 base_url 与 api_key 不同。本实现用 httpx 直接调用,避免引入额外 SDK。

不内置 retry / fallback(降级由调用方决定)。仅内置:
- 超时:asyncio.wait_for → LLMError(kind="timeout")
- 429:识别限流 → LLMError(kind="rate_limit")
- 401/403:识别鉴权 → LLMError(kind="auth")
- 其他网络错:→ LLMError(kind="network")
- 返回体格式异常:→ LLMError(kind="bad_response")
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.services.llm.base import LLMError, LLMResult, Message

logger = logging.getLogger(__name__)


# provider 名 → 默认 OpenAI-compatible endpoint
PROVIDER_DEFAULT_BASE_URL: dict[str, str] = {
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "openai": "https://api.openai.com/v1",
}


class OpenAICompatProvider:
    """OpenAI 兼容协议的 Provider(dashscope / openai / 其他兼容服务通用)。"""

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        model: str,
        base_url: str,
        timeout_s: float,
    ) -> None:
        self.name = name
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        if not self._api_key:
            return LLMResult(
                text="",
                error=LLMError(kind="auth", message="LLM_API_KEY 未配置"),
            )

        payload: dict[str, object] = {
            "model": self._model,
            "messages": list(messages),
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await asyncio.wait_for(
                    client.post(url, json=payload, headers=headers),
                    timeout=self._timeout_s,
                )
        except asyncio.TimeoutError:
            return LLMResult(
                text="",
                error=LLMError(kind="timeout", message=f"LLM 调用超时(>{self._timeout_s}s)"),
            )
        except httpx.HTTPError as exc:
            return LLMResult(
                text="",
                error=LLMError(
                    kind="network",
                    message=f"{type(exc).__name__}: {exc}"[:500] or type(exc).__name__,
                ),
            )

        if resp.status_code == 429:
            return LLMResult(
                text="",
                error=LLMError(
                    kind="rate_limit",
                    message=resp.text[:500],
                    status_code=429,
                ),
            )
        if resp.status_code in (401, 403):
            return LLMResult(
                text="",
                error=LLMError(
                    kind="auth",
                    message=resp.text[:500],
                    status_code=resp.status_code,
                ),
            )
        if resp.status_code >= 400:
            return LLMResult(
                text="",
                error=LLMError(
                    kind="other",
                    message=resp.text[:500],
                    status_code=resp.status_code,
                ),
            )

        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            return LLMResult(
                text="",
                error=LLMError(kind="bad_response", message=str(exc)[:500]),
            )

        return LLMResult(text=text, raw=data)
