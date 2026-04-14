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


async def trigger_pipeline(bidder_id: int) -> None:
    """触发 pipeline 后台协程。已 disabled 时 no-op。"""
    if _DISABLED:
        logger.info("pipeline disabled, skip trigger for bidder=%d", bidder_id)
        return
    asyncio.create_task(run_pipeline(bidder_id))


def is_disabled() -> bool:
    """测试探测用"""
    return _DISABLED


__all__ = ["trigger_pipeline", "is_disabled"]
