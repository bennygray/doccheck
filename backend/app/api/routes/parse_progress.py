"""C5 SSE 解析进度流。

GET /api/projects/{pid}/parse-progress → text/event-stream
首帧 `snapshot`,之后实时 publish bidder/document/rule/error/heartbeat 事件。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.services.parser.pipeline.progress_broker import progress_broker

logger = logging.getLogger(__name__)
router = APIRouter()

# 对齐 C1 sse_demo 的环境变量约定,L2 测试缩短
HEARTBEAT_INTERVAL_S = float(os.environ.get("SSE_HEARTBEAT_INTERVAL_S", "15.0"))


async def _fetch_visible_project(
    session: AsyncSession, user: User, project_id: int
) -> Project:
    stmt = get_visible_projects_stmt(user).where(Project.id == project_id)
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    return project


async def _build_snapshot(
    session: AsyncSession, project_id: int
) -> dict:
    """首帧:DB 当前 bidder 列表 + progress 计数。"""
    bidder_rows = (
        await session.execute(
            select(Bidder).where(
                Bidder.project_id == project_id,
                Bidder.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    bidders = [
        {
            "id": b.id,
            "parse_status": b.parse_status,
            "file_count": b.file_count,
        }
        for b in bidder_rows
    ]
    # progress 计数(用 parse_status 汇总)
    status_groups = (
        await session.execute(
            select(Bidder.parse_status, func.count(Bidder.id))
            .where(
                Bidder.project_id == project_id,
                Bidder.deleted_at.is_(None),
            )
            .group_by(Bidder.parse_status)
        )
    ).all()
    progress = _aggregate_progress(status_groups, total=len(bidder_rows))
    return {"bidders": bidders, "progress": progress}


def _aggregate_progress(status_groups, total: int) -> dict:
    """把 bidder.parse_status → ProjectProgress 形状。"""
    counts = {
        "pending_count": 0,
        "extracting_count": 0,
        "extracted_count": 0,
        "identifying_count": 0,
        "identified_count": 0,
        "pricing_count": 0,
        "priced_count": 0,
        "partial_count": 0,
        "failed_count": 0,
        "needs_password_count": 0,
    }
    for status_val, cnt in status_groups:
        if status_val == "pending":
            counts["pending_count"] += cnt
        elif status_val == "extracting":
            counts["extracting_count"] += cnt
        elif status_val == "extracted":
            counts["extracted_count"] += cnt
        elif status_val == "identifying":
            counts["identifying_count"] += cnt
        elif status_val == "identified":
            counts["identified_count"] += cnt
        elif status_val == "pricing":
            counts["pricing_count"] += cnt
        elif status_val == "priced":
            counts["priced_count"] += cnt
        elif status_val in ("partial", "price_partial"):
            counts["partial_count"] += cnt
        elif status_val in ("failed", "identify_failed", "price_failed"):
            counts["failed_count"] += cnt
        elif status_val == "needs_password":
            counts["needs_password_count"] += cnt
    return {"total_bidders": total, **counts}


def _format_sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _event_stream(request: Request, project_id: int):
    """SSE 主循环:首帧 snapshot → 订阅 broker → 超时推 heartbeat。"""
    # 首帧:重建 DB snapshot
    from app.db.session import async_session

    try:
        async with async_session() as session:
            snapshot = await _build_snapshot(session, project_id)
        yield _format_sse("snapshot", snapshot)

        queue = progress_broker.subscribe(project_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=HEARTBEAT_INTERVAL_S
                    )
                    yield _format_sse(event.event_type, event.data)
                except asyncio.TimeoutError:
                    ts = datetime.now(timezone.utc).isoformat()
                    yield _format_sse("heartbeat", {"ts": ts})
        finally:
            progress_broker.unsubscribe(project_id, queue)
    except asyncio.CancelledError:
        logger.info("SSE client disconnected project=%d", project_id)
        raise


@router.get("/{project_id}/parse-progress")
async def get_parse_progress(
    project_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE 长连接:订阅项目解析进度。"""
    await _fetch_visible_project(session, user, project_id)

    return StreamingResponse(
        _event_stream(request, project_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
