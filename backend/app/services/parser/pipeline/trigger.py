"""Pipeline 触发入口 (C5 parser-pipeline)

- trigger_pipeline: asyncio.create_task 后台起 run_pipeline
- INFRA_DISABLE_PIPELINE=1 时 no-op(L2 测试里直接 await run_pipeline)
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.services.parser.pipeline.run_pipeline import run_pipeline

logger = logging.getLogger(__name__)

_DISABLED = os.environ.get("INFRA_DISABLE_PIPELINE") == "1"

# 保持 task 引用,防止 GC 回收 + 注册 done callback 捕获异常
_background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]


def _task_done(task: asyncio.Task) -> None:  # type: ignore[type-arg]
    _background_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error(
            "pipeline task crashed: %s", task.exception(), exc_info=task.exception()
        )


async def trigger_pipeline(bidder_id: int) -> None:
    """触发 pipeline 后台协程。已 disabled 时 no-op。"""
    if _DISABLED:
        logger.info("pipeline disabled, skip trigger for bidder=%d", bidder_id)
        return
    task = asyncio.create_task(
        run_pipeline(bidder_id), name=f"pipeline-bidder-{bidder_id}"
    )
    _background_tasks.add(task)
    task.add_done_callback(_task_done)


def is_disabled() -> bool:
    """测试探测用"""
    return _DISABLED


__all__ = ["trigger_pipeline", "is_disabled"]
