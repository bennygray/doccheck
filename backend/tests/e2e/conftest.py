"""L2 E2E 测试 conftest - 使用真实 postgres(由 docker compose up -d db 提供)

若需要无 postgres 场景测其他 API,可在对应测试里覆盖 dependencies。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """ASGI 客户端,用于 L2 API E2E 测试"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _disable_l9_llm_by_default(monkeypatch):
    """C14: 默认 patch `judge_llm.call_llm_judge` 返 (None, None) 走降级,避免既有
    L2 测试触发真实 LLM 调用。C14 专属 e2e 测试显式覆盖此 patch(mock_llm_l9_ok 等)。

    等价于"原断言(total/level 纯公式 + llm_conclusion 占位)行为保持"。
    """
    from app.services.detect import judge_llm

    async def _fake(summary, formula_total, *, provider=None, cfg=None):
        return None, None

    monkeypatch.setattr(judge_llm, "call_llm_judge", _fake)
