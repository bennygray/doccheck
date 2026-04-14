"""L2: async_tasks scanner 重启恢复 E2E (C6 §11.9)

模拟 stuck async_tasks 行(手工 INSERT heartbeat_at 过期)→ 调 scan_and_recover → 验:
- extract / content_parse / llm_classify / agent_run 四种恢复路径
- 项目 analyzing → ready 回滚(agent_run)
- 单 handler 失败不影响其他
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.async_task import AsyncTask
from app.models.bidder import Bidder
from app.models.project import Project
from app.models.user import User
from app.services.async_tasks.scanner import scan_and_recover

pytestmark = pytest.mark.asyncio


async def _mk_stuck(
    subtype: str, entity_type: str, entity_id: int, minutes_ago: int = 5
) -> int:
    past = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    async with async_session() as s:
        t = AsyncTask(
            subtype=subtype,
            entity_type=entity_type,
            entity_id=entity_id,
            status="running",
            started_at=past,
            heartbeat_at=past,
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
        return t.id


async def test_scanner_recovers_analyzing_project_to_ready(
    seeded_reviewer: User, clean_users
):
    # 建 project analyzing + bidders + 所有 AgentTask running(stuck)
    async with async_session() as s:
        p = Project(
            name="p_scanner",
            status="analyzing",
            owner_id=seeded_reviewer.id,
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        bidders = []
        for i in range(2):
            b = Bidder(
                name=f"scn_b{i}",
                project_id=p.id,
                parse_status="identified",
            )
            s.add(b)
        await s.commit()
        bidder_rows = (
            await s.execute(
                select(Bidder).where(Bidder.project_id == p.id)
            )
        ).scalars().all()
        # 建 3 个 pair AgentTask running
        for _ in range(3):
            at = AgentTask(
                project_id=p.id,
                version=1,
                agent_name="text_similarity",
                agent_type="pair",
                pair_bidder_a_id=bidder_rows[0].id,
                pair_bidder_b_id=bidder_rows[1].id,
                status="running",
            )
            s.add(at)
        await s.commit()
        at_rows = (
            await s.execute(
                select(AgentTask).where(AgentTask.project_id == p.id)
            )
        ).scalars().all()
        at_ids = [a.id for a in at_rows]
        pid = p.id

    # 每个 AgentTask 都建 stuck async_tasks 行
    for at_id in at_ids:
        await _mk_stuck("agent_run", "agent_task", at_id)

    counts = await scan_and_recover()
    assert counts["agent_run"] == 3

    async with async_session() as s:
        project = await s.get(Project, pid)
        assert project.status == "ready"  # 全 terminate → 回 ready
        at_rows = (
            await s.execute(
                select(AgentTask).where(AgentTask.project_id == pid)
            )
        ).scalars().all()
        assert all(a.status == "timeout" for a in at_rows)


async def test_scanner_marks_async_task_timeout(
    seeded_reviewer: User, clean_users
):
    """async_tasks 行被标 status=timeout + finished_at 非空。"""
    async with async_session() as s:
        p = Project(
            name="p_timeout", status="parsing", owner_id=seeded_reviewer.id
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        b = Bidder(
            name="scn_tm", project_id=p.id, parse_status="extracting"
        )
        s.add(b)
        await s.commit()
        await s.refresh(b)
        bid = b.id

    atid = await _mk_stuck("extract", "bidder", bid)
    await scan_and_recover()

    async with async_session() as s:
        row = await s.get(AsyncTask, atid)
        assert row.status == "timeout"
        assert row.finished_at is not None
        assert row.error is not None


async def test_scanner_handler_no_throw_on_missing_entity(
    clean_users,
):
    """entity 已被删除 → handler get None,no-op;行仍标 timeout。"""
    atid = await _mk_stuck("extract", "bidder", 999_999)  # 不存在
    counts = await scan_and_recover()
    assert counts["extract"] == 1
    assert counts["error"] == 0
    async with async_session() as s:
        row = await s.get(AsyncTask, atid)
        assert row.status == "timeout"
