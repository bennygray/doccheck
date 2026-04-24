"""L1:price_parsing_rules schema migration(parser-accuracy-fixes P1-5/H2)

验证 alembic 0011 升/降级:
- upgrade:加 sheets_config JSONB 列,老 3 列 nullable=True
- downgrade:drop sheets_config,老 3 列恢复 NOT NULL

用 alembic `command.upgrade/downgrade` + asyncpg 直连查 information_schema。
注意:env.py 把 sqlalchemy.url 绑到 `settings.database_url`(dev DB),
所以本测试实际跑在 dev DB 上;若要独立 testdb,需改 env.py 支持 env override。
当前 skip 条件:不在 testdb context 则跳(避免污染 dev DB)。
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="需 TEST_DATABASE_URL 环境变量指向 PostgreSQL testdb",
)


def _pg_dsn() -> str:
    """把 asyncpg URL 转纯 postgresql:// DSN(asyncpg 默认接受)。"""
    url = os.environ["TEST_DATABASE_URL"]
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _get_column_nullability() -> dict[str, str]:
    """查 price_parsing_rules 列 nullability;返 {column_name: 'YES'/'NO'}"""
    import asyncpg

    conn = await asyncpg.connect(_pg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT column_name, is_nullable FROM information_schema.columns
            WHERE table_name = 'price_parsing_rules'
              AND column_name IN ('sheets_config', 'sheet_name', 'header_row', 'column_mapping')
            """
        )
        return {r["column_name"]: r["is_nullable"] for r in rows}
    finally:
        await conn.close()


def _run_alembic(direction: str, target: str) -> None:
    """通过子进程跑 alembic,避免 asyncio.run 嵌套 pytest 事件循环。"""
    import subprocess

    env = os.environ.copy()
    env["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    result = subprocess.run(
        ["uv", "run", "alembic", direction, target],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/..",
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {direction} {target} failed:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


@pytest.mark.asyncio
async def test_upgrade_adds_sheets_config_and_nulls_legacy():
    """upgrade 后:sheets_config 列存在,3 老列 nullable=YES"""
    _run_alembic("upgrade", "head")
    cols = await _get_column_nullability()
    assert "sheets_config" in cols
    assert cols["sheet_name"] == "YES"
    assert cols["header_row"] == "YES"
    assert cols["column_mapping"] == "YES"


@pytest.mark.asyncio
async def test_downgrade_drops_sheets_config_restores_not_null():
    """downgrade 后:sheets_config drop,3 老列恢复 NOT NULL"""
    _run_alembic("upgrade", "head")
    _run_alembic("downgrade", "0010_llm_default")
    cols = await _get_column_nullability()
    assert "sheets_config" not in cols
    assert cols["sheet_name"] == "NO"
    assert cols["header_row"] == "NO"
    assert cols["column_mapping"] == "NO"
    # 恢复 head 给其他测试
    _run_alembic("upgrade", "head")


@pytest.mark.asyncio
async def test_upgrade_idempotent_after_downgrade():
    """升 → 降 → 升 可重复,最终仍在 head"""
    import asyncpg

    _run_alembic("upgrade", "head")
    _run_alembic("downgrade", "0010_llm_default")
    _run_alembic("upgrade", "head")

    conn = await asyncpg.connect(_pg_dsn())
    try:
        current = await conn.fetchval("SELECT version_num FROM alembic_version")
        assert current == "0011_prr_sheets_config"
    finally:
        await conn.close()
