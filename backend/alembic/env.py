"""Alembic async 迁移环境 - C1 infra-base

- 从 app.core.config.settings 读取 DATABASE_URL(与运行时 db/session.py 统一)
- 使用 asyncpg driver + async_engine_from_config + run_sync 模式
- target_metadata = Base.metadata(C1 阶段暂无业务 model,仅建 alembic_version 表)
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.db.base import Base

config = context.config
# 从应用配置注入 URL,覆盖 alembic.ini 中的占位
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# C1 阶段 Base.metadata 为空(无业务 model),后续 change 注册 model 后会自动纳入
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式(生成 SQL 脚本,不连 DB)"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
