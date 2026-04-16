"""SystemConfig 读取器 (C17 admin-users)

提供 get_active_rules()：查 DB 单行 → 若无则返回默认配置。
引擎层在检测前调用一次，避免各 agent 分别查 DB。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_config import SystemConfig
from app.services.admin.rules_defaults import DEFAULT_RULES_CONFIG


async def get_active_rules(session: AsyncSession) -> dict:
    """读取当前生效的规则配置。

    SystemConfig 表为空或 config 字段为空时返回内置默认值。
    """
    stmt = select(SystemConfig).where(SystemConfig.id == 1)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None or not row.config:
        return DEFAULT_RULES_CONFIG
    return row.config
