"""L1 - async_tasks/tracker 单元测试 (C6 §9.5)

需要真实 DB。验证:
- 正常退出 → status='done', finished_at 非空
- 异常退出 → status='failed', error 非空,异常重抛
- 心跳 UPDATE heartbeat_at
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.async_task import AsyncTask
from app.services.async_tasks.tracker import track

pytestmark = pytest.mark.asyncio


async def _get_task(task_id: int) -> AsyncTask | None:
    async with async_session() as s:
        return (
            await s.execute(select(AsyncTask).where(AsyncTask.id == task_id))
        ).scalar_one_or_none()


async def _cleanup():
    from sqlalchemy import delete

    async with async_session() as s:
        await s.execute(delete(AsyncTask))
        await s.commit()


async def test_normal_exit_marks_done():
    await _cleanup()
    async with track(subtype="extract", entity_type="bidder", entity_id=42) as tid:
        assert tid > 0
        # 在上下文内 task 状态应该是 running
        row = await _get_task(tid)
        assert row is not None
        assert row.status == "running"

    # 退出后 done
    row = await _get_task(tid)
    assert row is not None
    assert row.status == "done"
    assert row.finished_at is not None
    assert row.error is None


async def test_exception_marks_failed_and_reraises():
    await _cleanup()
    task_id_captured: list[int] = []

    with pytest.raises(ValueError, match="boom"):
        async with track(
            subtype="content_parse",
            entity_type="bid_document",
            entity_id=100,
        ) as tid:
            task_id_captured.append(tid)
            raise ValueError("boom")

    assert len(task_id_captured) == 1
    row = await _get_task(task_id_captured[0])
    assert row is not None
    assert row.status == "failed"
    assert row.error is not None
    assert "boom" in row.error


async def test_heartbeat_updates(monkeypatch):
    """缩短 heartbeat 到 0.1s,在上下文里 sleep 0.3s,验 heartbeat_at 更新。"""
    await _cleanup()
    monkeypatch.setenv("ASYNC_TASK_HEARTBEAT_S", "0.1")

    async with track(subtype="llm_classify", entity_type="bidder", entity_id=7) as tid:
        row_start = await _get_task(tid)
        assert row_start is not None
        hb0 = row_start.heartbeat_at
        await asyncio.sleep(0.4)
        row_mid = await _get_task(tid)
        assert row_mid is not None
        # heartbeat_at 应该已被心跳协程更新
        assert row_mid.heartbeat_at > hb0
