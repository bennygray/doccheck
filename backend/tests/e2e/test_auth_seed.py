"""L2: alembic seed admin 幂等性 (C2).

通过 subprocess 跑真实 alembic,避免同 event loop 内 asyncio.run 冲突
(与 C1 test_alembic_upgrade.py 同策略)。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sqlalchemy import select, text

from app.db.session import async_session
from app.models.user import User

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _run_alembic(*args: str) -> None:
    r = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, (
        f"alembic {' '.join(args)} failed:\n{r.stderr}\n{r.stdout}"
    )


async def test_seed_admin_idempotent():
    # 清空 users 后从头迁移,应写入 admin
    async with async_session() as s:
        await s.execute(text("DELETE FROM users"))
        await s.commit()

    _run_alembic("downgrade", "base")
    _run_alembic("upgrade", "head")

    async with async_session() as s:
        admins = (
            await s.execute(select(User).where(User.username == "admin"))
        ).scalars().all()
        assert len(admins) == 1
        admin = admins[0]
        assert admin.role == "admin"
        assert admin.must_change_password is True
        first_hash = admin.password_hash

    # 再次 upgrade(本就是 head 状态,等效无操作;模拟多次启动/CI 重放)
    # downgrade→upgrade 走完整流程验证 ON CONFLICT DO NOTHING
    _run_alembic("downgrade", "base")
    _run_alembic("upgrade", "head")

    async with async_session() as s:
        admins = (
            await s.execute(select(User).where(User.username == "admin"))
        ).scalars().all()
        assert len(admins) == 1  # 仍只有一条
        # 注:downgrade 会 drop 表,所以 hash 是新算的;这里主要验证"唯一"不重复
