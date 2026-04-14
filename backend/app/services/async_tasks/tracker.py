"""通用异步任务心跳追踪 (C6 detect-framework D3)

上下文管理器 `async with track(subtype, entity_type, entity_id):` 进入即 INSERT
一行 async_tasks,启后台心跳协程(默认 30s)更新 heartbeat_at;退出时更新终态。

- 正常退出:status='done', finished_at=now()
- 异常退出:status='failed', error=str(exc)[:500];**异常重新抛出**

心跳间隔可被 `ASYNC_TASK_HEARTBEAT_S` 环境变量覆盖(L2 测试缩到秒级)。
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.async_task import AsyncTask

logger = logging.getLogger(__name__)


def _heartbeat_interval() -> float:
    try:
        return float(os.environ.get("ASYNC_TASK_HEARTBEAT_S", "30"))
    except ValueError:
        return 30.0


async def _insert_task_row(
    session: AsyncSession,
    subtype: str,
    entity_type: str,
    entity_id: int,
) -> int:
    now = datetime.now(timezone.utc)
    task = AsyncTask(
        subtype=subtype,
        entity_type=entity_type,
        entity_id=entity_id,
        status="running",
        started_at=now,
        heartbeat_at=now,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task.id


async def _heartbeat_loop(task_id: int, interval_s: float) -> None:
    """后台协程:每 interval_s 秒 UPDATE heartbeat_at。"""
    try:
        while True:
            await asyncio.sleep(interval_s)
            async with async_session() as session:
                stmt = (
                    update(AsyncTask)
                    .where(AsyncTask.id == task_id)
                    .values(heartbeat_at=datetime.now(timezone.utc))
                )
                await session.execute(stmt)
                await session.commit()
    except asyncio.CancelledError:
        # 正常被取消(上下文退出)
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("async_tasks heartbeat error task=%s: %s", task_id, exc)


async def _finalize_task(task_id: int, status: str, error: str | None) -> None:
    """更新终态(status + finished_at + error)。"""
    async with async_session() as session:
        stmt = (
            update(AsyncTask)
            .where(AsyncTask.id == task_id)
            .values(
                status=status,
                finished_at=datetime.now(timezone.utc),
                error=(error[:500] if error else None),
            )
        )
        await session.execute(stmt)
        await session.commit()


@asynccontextmanager
async def track(
    subtype: str,
    entity_type: str,
    entity_id: int,
) -> AsyncIterator[int]:
    """上下文管理器:INSERT AsyncTask 行 + 心跳 + finally 更新终态。

    用法:
        async with track("extract", "bidder", bidder_id):
            ...长跑业务...

    返回 task_id(yielded),业务代码一般不用直接读,但测试可 assert 行存在。
    """
    async with async_session() as session:
        task_id = await _insert_task_row(session, subtype, entity_type, entity_id)

    interval = _heartbeat_interval()
    hb_task: asyncio.Task[None] | None = None
    if interval > 0:
        hb_task = asyncio.create_task(_heartbeat_loop(task_id, interval))

    try:
        yield task_id
    except BaseException as exc:
        await _finalize_task(
            task_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        # 异常重抛(tracker 不吞异常)
        raise
    else:
        await _finalize_task(task_id, status="done", error=None)
    finally:
        if hb_task is not None:
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):
                pass


__all__ = ["track"]
