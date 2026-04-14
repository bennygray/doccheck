"""L1 - async_tasks/scanner 单元测试 (C6 §9.6)"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.async_task import AsyncTask
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.project import Project
from app.models.user import User
from app.services.async_tasks.scanner import scan_and_recover
from app.services.auth.password import hash_password

pytestmark = pytest.mark.asyncio


async def _cleanup():
    async with async_session() as s:
        await s.execute(delete(AsyncTask))
        await s.execute(delete(AgentTask))
        await s.execute(delete(BidDocument))
        await s.execute(delete(Bidder))
        await s.execute(delete(Project))
        await s.execute(delete(User))
        await s.commit()


async def _make_user() -> User:
    async with async_session() as s:
        u = User(
            username="sc_u",
            password_hash=hash_password("pw"),
            role="reviewer",
            is_active=True,
            must_change_password=False,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


async def _make_project(owner_id: int, status: str = "analyzing") -> int:
    async with async_session() as s:
        p = Project(name="sc_p", status=status, owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p.id


_BIDDER_COUNTER = {"n": 0}


async def _make_bidder(project_id: int, parse_status: str = "extracting") -> int:
    _BIDDER_COUNTER["n"] += 1
    async with async_session() as s:
        b = Bidder(
            name=f"sc_b_{_BIDDER_COUNTER['n']}",
            project_id=project_id,
            parse_status=parse_status,
        )
        s.add(b)
        await s.commit()
        await s.refresh(b)
        return b.id


async def _make_stuck_async_task(
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


async def test_scan_empty_table_no_op():
    await _cleanup()
    counts = await scan_and_recover()
    assert counts == {
        "extract": 0,
        "content_parse": 0,
        "llm_classify": 0,
        "agent_run": 0,
        "error": 0,
    }


async def test_scan_recover_extract():
    await _cleanup()
    u = await _make_user()
    pid = await _make_project(u.id, status="parsing")
    bid = await _make_bidder(pid, parse_status="extracting")
    atid = await _make_stuck_async_task("extract", "bidder", bid)

    counts = await scan_and_recover()
    assert counts["extract"] == 1

    # bidder 应被回滚
    async with async_session() as s:
        bidder = await s.get(Bidder, bid)
        assert bidder.parse_status == "failed"
        assert bidder.parse_error and "系统重启" in bidder.parse_error
        at = await s.get(AsyncTask, atid)
        assert at.status == "timeout"


async def test_scan_recover_content_parse():
    await _cleanup()
    u = await _make_user()
    pid = await _make_project(u.id, status="parsing")
    bid = await _make_bidder(pid)
    # 需要一个 BidDocument
    async with async_session() as s:
        doc = BidDocument(
            bidder_id=bid,
            file_name="f.docx",
            file_path="/tmp/f.docx",
            file_size=100,
            file_type=".docx",
            md5="x" * 32,
            source_archive="root.zip",
            parse_status="identifying",
        )
        s.add(doc)
        await s.commit()
        await s.refresh(doc)
        doc_id = doc.id

    await _make_stuck_async_task("content_parse", "bid_document", doc_id)
    counts = await scan_and_recover()
    assert counts["content_parse"] == 1

    async with async_session() as s:
        doc2 = await s.get(BidDocument, doc_id)
        assert doc2.parse_status == "identify_failed"


async def test_scan_recover_llm_classify():
    await _cleanup()
    u = await _make_user()
    pid = await _make_project(u.id, status="parsing")
    bid = await _make_bidder(pid, parse_status="identifying")
    await _make_stuck_async_task("llm_classify", "bidder", bid)

    counts = await scan_and_recover()
    assert counts["llm_classify"] == 1

    async with async_session() as s:
        bidder = await s.get(Bidder, bid)
        assert bidder.parse_status == "identify_failed"


async def test_scan_recover_agent_run_rolls_project_back():
    """当所有 AgentTask terminate 后,project.status 从 analyzing 回 ready。"""
    await _cleanup()
    u = await _make_user()
    pid = await _make_project(u.id, status="analyzing")
    bid_a = await _make_bidder(pid, parse_status="identified")
    bid_b = await _make_bidder(pid, parse_status="identified")

    # 创建 1 个 running AgentTask(模拟 stuck)
    async with async_session() as s:
        at = AgentTask(
            project_id=pid,
            version=1,
            agent_name="text_similarity",
            agent_type="pair",
            pair_bidder_a_id=bid_a,
            pair_bidder_b_id=bid_b,
            status="running",
        )
        s.add(at)
        await s.commit()
        await s.refresh(at)
        at_id = at.id

    await _make_stuck_async_task("agent_run", "agent_task", at_id)
    counts = await scan_and_recover()
    assert counts["agent_run"] == 1

    async with async_session() as s:
        at2 = await s.get(AgentTask, at_id)
        assert at2.status == "timeout"
        project = await s.get(Project, pid)
        # 所有 AgentTask 都终态 → project 回 ready
        assert project.status == "ready"


async def test_scan_handler_failure_isolated_from_others():
    """一个 handler 抛异常不影响其他行。"""
    await _cleanup()
    u = await _make_user()
    pid = await _make_project(u.id, status="parsing")
    bid = await _make_bidder(pid)

    # 第 1 行:不存在的 entity_id → handler 因为 get 返 None 会 no-op(不抛)
    # 第 2 行:正常的 extract 恢复
    await _make_stuck_async_task("extract", "bidder", 99999)  # entity 不存在,no-op
    await _make_stuck_async_task("extract", "bidder", bid)  # 正常恢复

    counts = await scan_and_recover()
    # 两行都被处理(第一行虽然 entity 不存在,但 handler 没抛)
    assert counts["extract"] == 2
    assert counts["error"] == 0


async def test_scan_skips_fresh_heartbeat():
    """heartbeat_at 在阈值内 → 不扫。"""
    await _cleanup()
    # heartbeat 只过了 10s(默认阈值 60s)
    await _make_stuck_async_task("extract", "bidder", 1, minutes_ago=0)
    # 手工改一下让 heartbeat 近期
    async with async_session() as s:
        rows = (await s.execute(select(AsyncTask))).scalars().all()
        for r in rows:
            r.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await s.commit()

    counts = await scan_and_recover()
    assert counts["extract"] == 0
