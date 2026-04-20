"""LLM 测试连接 (admin-llm-config Q3)

发送极短 prompt 验证 provider+key+base_url 可用,返 (ok, latency_ms, error)。
"""

from __future__ import annotations

import time

from app.services.llm.openai_compat import (
    PROVIDER_DEFAULT_BASE_URL,
    OpenAICompatProvider,
)


async def test_connection(
    *,
    provider: str,
    api_key: str,
    model: str,
    base_url: str | None,
    timeout_s: int = 10,
) -> tuple[bool, int, str | None]:
    """发 "ping" 请求 + max_tokens=1,最省 token。

    - 超时上限强制 ≤ 10s(防止卡 UI)
    - 捕获所有异常转字符串,截断 200 字符
    - 200 OK 且 LLMResult 无 error → ok=True
    """
    # base_url 回退
    resolved_base = base_url or PROVIDER_DEFAULT_BASE_URL.get(provider)
    if resolved_base is None:
        return (
            False,
            0,
            f"未知 provider '{provider}',请显式填写 base_url",
        )

    effective_timeout = min(timeout_s, 10)

    t0 = time.time()
    try:
        tmp_provider = OpenAICompatProvider(
            name=provider,
            api_key=api_key or "",
            model=model,
            base_url=resolved_base,
            timeout_s=float(effective_timeout),
        )
        result = await tmp_provider.complete(
            [{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
    except Exception as exc:  # noqa: BLE001 - tester 需吞所有异常转字符串
        latency = int((time.time() - t0) * 1000)
        return (False, latency, f"{type(exc).__name__}: {str(exc)[:180]}")

    latency_ms = int((time.time() - t0) * 1000)
    if result.error is not None:
        return (
            False,
            latency_ms,
            f"[{result.error.kind}] {result.error.message[:180]}",
        )
    return (True, latency_ms, None)
