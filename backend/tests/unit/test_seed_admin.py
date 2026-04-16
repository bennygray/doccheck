"""DEF-003: seed admin 单元测试"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.session import async_session
from app.models.user import User
from app.services.auth.seed import ensure_seed_admin


async def _count_users() -> int:
    async with async_session() as s:
        return (await s.execute(select(func.count()).select_from(User))).scalar_one()


async def _delete_all_users() -> None:
    from sqlalchemy import delete

    async with async_session() as s:
        await s.execute(delete(User))
        await s.commit()


@pytest.fixture(autouse=True)
async def _clean():
    await _delete_all_users()
    yield
    await _delete_all_users()


# -- 2.1: users 表为空 → 创建 admin --

async def test_seed_creates_admin_when_empty():
    assert await _count_users() == 0

    result = await ensure_seed_admin()

    assert result is True
    assert await _count_users() == 1


# -- 2.2: users 表已有用户 → 不创建 --

async def test_seed_skips_when_users_exist():
    # 先 seed 一次
    await ensure_seed_admin()
    assert await _count_users() == 1

    # 再调不会重复创建
    result = await ensure_seed_admin()

    assert result is False
    assert await _count_users() == 1


# -- 2.3: 创建的用户属性正确 --

async def test_seed_user_attributes():
    await ensure_seed_admin()

    async with async_session() as s:
        user = (await s.execute(select(User))).scalar_one()

    assert user.username == "admin"
    assert user.role == "admin"
    assert user.is_active is True
    assert user.must_change_password is True
