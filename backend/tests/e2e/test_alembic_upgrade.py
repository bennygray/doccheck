"""L2: alembic upgrade head 后 alembic_version 表存在(走 subprocess 跑真实 CLI)"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.session import engine


@pytest.mark.asyncio
async def test_alembic_upgrade_head_creates_version_table() -> None:
    backend_root = Path(__file__).resolve().parents[2]

    # 用 subprocess 跑 `alembic upgrade head`:避免在 pytest-asyncio 的 loop 里再开 asyncio.run
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed\nstdout={result.stdout}\nstderr={result.stderr}"
    )

    # 验证 alembic_version 表存在(走 async engine,和运行时一致)
    async with engine.connect() as conn:
        result_rows = await conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='alembic_version'"
            )
        )
        row = result_rows.first()
        assert row is not None, "alembic_version 表不存在"
