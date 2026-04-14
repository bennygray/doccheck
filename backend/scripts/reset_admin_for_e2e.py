"""E2E globalSetup 辅助脚本:把 admin 用户复位到干净初始状态。

用途:每次 Playwright 启动前通过 execSync 调用,保证测试可重复。
- password → admin123
- must_change_password → true
- login_fail_count → 0
- locked_until → NULL
- is_active → true

运行方式:`uv run python -m scripts.reset_admin_for_e2e`(在 backend 目录)
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.core.config import settings
from app.db.session import async_session
from app.services.auth.password import hash_password


async def main() -> None:
    new_hash = hash_password(settings.auth_seed_admin_password)
    async with async_session() as s:
        result = await s.execute(
            text(
                """
                UPDATE users SET
                    password_hash = :h,
                    must_change_password = TRUE,
                    login_fail_count = 0,
                    locked_until = NULL,
                    is_active = TRUE,
                    password_changed_at = NOW()
                WHERE username = :u
                """
            ),
            {"h": new_hash, "u": settings.auth_seed_admin_username},
        )
        await s.commit()
        if result.rowcount == 0:
            # admin 被删过?通过 alembic seed 逻辑补回
            await s.execute(
                text(
                    """
                    INSERT INTO users
                        (username, password_hash, role, is_active, must_change_password)
                    VALUES (:u, :h, 'admin', TRUE, TRUE)
                    ON CONFLICT (username) DO NOTHING
                    """
                ),
                {"u": settings.auth_seed_admin_username, "h": new_hash},
            )
            await s.commit()
    print(f"[reset-admin-for-e2e] admin reset to {settings.auth_seed_admin_password}")


if __name__ == "__main__":
    asyncio.run(main())
