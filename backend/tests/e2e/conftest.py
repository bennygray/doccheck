"""L2 E2E 测试 conftest - 使用真实 postgres(由 docker compose up -d db 提供)

若需要无 postgres 场景测其他 API,可在对应测试里覆盖 dependencies。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.main import app


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """ASGI 客户端,用于 L2 API E2E 测试"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture(autouse=True)
async def _c15_cleanup():
    """C15: 新增 audit_logs / export_jobs / export_templates 表可能有 FK 引用
    analysis_reports / projects。为避免跨测试 FK 冲突(其他 test fixture 删
    AR/Project 时 audit_log 行仍在),每个 e2e 测试前后清理这三张 C15 新表。
    """
    from app.db.session import async_session
    from app.models.audit_log import AuditLog
    from app.models.export_job import ExportJob
    from app.models.export_template import ExportTemplate

    async with async_session() as s:
        for M in (ExportJob, AuditLog, ExportTemplate):
            await s.execute(delete(M))
        await s.commit()
    yield
    async with async_session() as s:
        for M in (ExportJob, AuditLog, ExportTemplate):
            await s.execute(delete(M))
        await s.commit()


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
