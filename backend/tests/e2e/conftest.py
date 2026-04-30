"""L2 E2E 测试 conftest - harden-async-infra N5:使用独立 testdb

启动方式:
  1) docker-compose -f docker-compose.test.yml up -d
  2) export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/documentcheck_test
  3) pytest tests/e2e/

`pytest_configure`(tests/conftest.py)会在未设 TEST_DATABASE_URL 时 loud exit=2,
不会静默退回 dev DB。

session-scoped fixture 启动时 `alembic upgrade head` 建/升级 schema;
之后 module 级 `testdb_clean`(autouse)每个 test module 前 TRUNCATE 所有 user 表。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from app.main import app


@pytest.fixture(scope="session", autouse=True)
def _testdb_schema():
    """session 启动时 alembic upgrade head,建 schema。

    `tests/conftest.py` 模块顶层已把 `DATABASE_URL` 设为 `TEST_DATABASE_URL`
    (当 sys.argv 含 tests/e2e 时);若 pytest 不带路径参数跑全量,顶层判断失效,
    **此处必须 loud-fail** 防静默退回 dev DB(reviewer H1)。
    """
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.exit(
            "TEST_DATABASE_URL not set (collected e2e tests). "
            "Run `docker-compose -f docker-compose.test.yml up -d` then "
            "`export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres"
            "@localhost:55432/documentcheck_test`",
            returncode=2,
        )
    # DATABASE_URL 可能被顶层 conftest 覆盖过;若跑全量场景未触发覆盖,此处补
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    alembic_ini = os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
    cfg = Config(os.path.abspath(alembic_ini))
    command.upgrade(cfg, "head")
    yield


@pytest_asyncio.fixture
async def testdb_clean():
    """module 级清理:TRUNCATE 所有业务表 RESTART IDENTITY CASCADE。

    非 autouse — 每个 e2e 测试文件若要确定性隔离 clean state,显式 depend 这个 fixture。
    既有 fixture(如 `_c15_cleanup` autouse)已处理大部分跨测试清理,此 fixture 作为
    更彻底的 reset 选项。
    """
    from app.db.session import async_session

    async with async_session() as s:
        # 获取所有用户表名(public schema 下非 alembic_version)
        rows = await s.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname='public' AND tablename <> 'alembic_version'"
            )
        )
        tables = [r[0] for r in rows]
        if tables:
            quoted = ", ".join(f'"{t}"' for t in tables)
            await s.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
            await s.commit()
    yield


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

    detect-tender-baseline: 扩展加 tender_documents(FK 到 projects)同步清理。
    """
    from app.db.session import async_session
    from app.models.audit_log import AuditLog
    from app.models.export_job import ExportJob
    from app.models.export_template import ExportTemplate
    from app.models.tender_document import TenderDocument

    async with async_session() as s:
        for M in (ExportJob, AuditLog, ExportTemplate, TenderDocument):
            await s.execute(delete(M))
        await s.commit()
    yield
    async with async_session() as s:
        for M in (ExportJob, AuditLog, ExportTemplate, TenderDocument):
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
