"""DEF-001: 项目状态自动流转 单元测试

测试 project_status_sync 模块的 try_transition_project_ready / try_transition_project_parsing。
"""

from __future__ import annotations

import pytest

from app.db.session import async_session
from app.models.bidder import Bidder
from app.models.project import Project
from app.models.user import User
from app.services.auth.password import hash_password
from app.services.parser.pipeline.project_status_sync import (
    try_transition_project_parsing,
    try_transition_project_ready,
)


@pytest.fixture
async def _seed_user():
    """创建一个 owner 用户,返回 user_id。"""
    async with async_session() as s:
        u = User(
            username="test_sync",
            password_hash=hash_password("x"),
            role="admin",
            is_active=True,
            must_change_password=False,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id


@pytest.fixture
async def project_factory(_seed_user: int):
    """工厂: 创建 project 并返回 id。"""
    created: list[int] = []

    async def _make(status: str = "draft") -> int:
        async with async_session() as s:
            p = Project(
                name="test",
                bid_code="T-001",
                status=status,
                owner_id=_seed_user,
            )
            s.add(p)
            await s.commit()
            await s.refresh(p)
            created.append(p.id)
            return p.id

    yield _make

    # cleanup
    async with async_session() as s:
        for pid in created:
            p = await s.get(Project, pid)
            if p:
                await s.delete(p)
        u = await s.get(User, _seed_user)
        if u:
            await s.delete(u)
        await s.commit()


@pytest.fixture
async def bidder_factory():
    """工厂: 给 project 添加 bidder。"""
    created: list[int] = []

    async def _make(project_id: int, name: str, parse_status: str = "pending") -> int:
        async with async_session() as s:
            b = Bidder(
                project_id=project_id,
                name=name,
                parse_status=parse_status,
            )
            s.add(b)
            await s.commit()
            await s.refresh(b)
            created.append(b.id)
            return b.id

    yield _make

    async with async_session() as s:
        for bid in created:
            b = await s.get(Bidder, bid)
            if b:
                await s.delete(b)
        await s.commit()


async def _get_project_status(pid: int) -> str:
    async with async_session() as s:
        p = await s.get(Project, pid)
        return p.status


# ── 2.1: 所有 bidder 终态 → ready ──

async def test_all_bidders_terminal_transitions_to_ready(
    project_factory, bidder_factory
):
    pid = await project_factory("parsing")
    await bidder_factory(pid, "A", "identified")
    await bidder_factory(pid, "B", "priced")

    result = await try_transition_project_ready(pid)

    assert result is True
    assert await _get_project_status(pid) == "ready"


# ── 2.2: 部分 bidder 仍在解析 → 不变 ──

async def test_partial_bidders_no_transition(
    project_factory, bidder_factory
):
    pid = await project_factory("parsing")
    await bidder_factory(pid, "A", "identified")
    await bidder_factory(pid, "B", "extracting")

    result = await try_transition_project_ready(pid)

    assert result is False
    assert await _get_project_status(pid) == "parsing"


# ── 2.3: 含失败 bidder → 仍触发 ready ──

async def test_failed_bidder_still_triggers_ready(
    project_factory, bidder_factory
):
    pid = await project_factory("draft")
    await bidder_factory(pid, "A", "identified")
    await bidder_factory(pid, "B", "identify_failed")

    result = await try_transition_project_ready(pid)

    assert result is True
    assert await _get_project_status(pid) == "ready"


# ── 2.4: 单个 bidder → 终态即触发 ──

async def test_single_bidder_terminal_triggers_ready(
    project_factory, bidder_factory
):
    pid = await project_factory("parsing")
    await bidder_factory(pid, "A", "priced")

    result = await try_transition_project_ready(pid)

    assert result is True
    assert await _get_project_status(pid) == "ready"


# ── 2.5: draft → parsing ──

async def test_draft_to_parsing(project_factory):
    pid = await project_factory("draft")

    result = await try_transition_project_parsing(pid)

    assert result is True
    assert await _get_project_status(pid) == "parsing"


async def test_parsing_to_parsing_noop(project_factory):
    """已经是 parsing 状态,不重复更新。"""
    pid = await project_factory("parsing")

    result = await try_transition_project_parsing(pid)

    assert result is False
    assert await _get_project_status(pid) == "parsing"


# ── 额外边界 ──

async def test_ready_project_not_re_transitioned(
    project_factory, bidder_factory
):
    """已经 ready 的项目不被重复流转。"""
    pid = await project_factory("ready")
    await bidder_factory(pid, "A", "identified")

    result = await try_transition_project_ready(pid)

    assert result is False
    assert await _get_project_status(pid) == "ready"


async def test_no_bidders_no_transition(project_factory):
    """无 bidder 的项目不流转。"""
    pid = await project_factory("draft")

    result = await try_transition_project_ready(pid)

    assert result is False
    assert await _get_project_status(pid) == "draft"
