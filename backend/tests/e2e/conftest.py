"""L2 E2E 测试 conftest - 使用真实 postgres(由 docker compose up -d db 提供)

若需要无 postgres 场景测其他 API,可在对应测试里覆盖 dependencies。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """ASGI 客户端,用于 L2 API E2E 测试"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
