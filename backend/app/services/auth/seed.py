"""系统启动 seed 管理员 (DEF-003 fix)

首次启动时检测 users 表是否为空，若空则自动创建管理员账号。
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import async_session
from app.models.user import User
from app.services.auth.password import hash_password

logger = logging.getLogger(__name__)


async def ensure_seed_admin() -> bool:
    """若 users 表为空则创建 seed admin。

    Returns:
        True 如果本次调用创建了用户。
    """
    async with async_session() as session:
        count = (
            await session.execute(select(func.count()).select_from(User))
        ).scalar_one()

        if count > 0:
            logger.debug("users table has %d rows, skip seed", count)
            return False

        user = User(
            username=settings.auth_seed_admin_username,
            password_hash=hash_password(settings.auth_seed_admin_password),
            role="admin",
            is_active=True,
            must_change_password=True,
        )
        session.add(user)
        await session.commit()
        logger.info(
            "seed admin created: username=%s (must_change_password=True)",
            settings.auth_seed_admin_username,
        )
        return True
