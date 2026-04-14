"""C6 检测 API (detect-framework)

端点:
- POST /api/projects/{pid}/analysis/start  — 启动检测(前置校验 + AgentTask 批量 INSERT + 异步调度)
- GET  /api/projects/{pid}/analysis/status — 当前 version AgentTask 快照
- GET  /api/projects/{pid}/analysis/events — SSE 事件流(agent_status / report_ready / heartbeat)
"""

from __future__ import annotations

import asyncio
import itertools
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
from app.models.agent_task import AgentTask
from app.models.bidder import Bidder
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.schemas.agent_task import AgentTaskResponse
from app.schemas.analysis import (
    AnalysisStartConflictResponse,
    AnalysisStartResponse,
    AnalysisStatusResponse,
)
from app.services.detect import agents as _detect_agents  # noqa: F401 - 触发 10 Agent 注册
from app.services.detect.engine import detect_disabled, run_detection
from app.services.detect.registry import AGENT_REGISTRY
from app.services.parser.pipeline.progress_broker import progress_broker

logger = logging.getLogger(__name__)
router = APIRouter()

# bidder 终态集 — 允许启动检测的前提
_BIDDER_TERMINAL_STATES = frozenset(
    {
        "identified",
        "priced",
        "price_partial",
        "identify_failed",
        "price_failed",
        "skipped",
        "needs_password",
        "failed",
        "extracted",  # 无 C5 LLM 时允许(文件 role=other)
        "partial",
    }
)

# 允许启动检测的项目 status
_PROJECT_START_ALLOWED = frozenset({"ready", "completed", "extracted"})

HEARTBEAT_INTERVAL_S = float(os.environ.get("SSE_HEARTBEAT_INTERVAL_S", "15.0"))


async def _fetch_visible_project(
    session: AsyncSession, user: User, project_id: int
) -> Project:
    stmt = get_visible_projects_stmt(user).where(Project.id == project_id)
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    return project


# --------------------- POST /analysis/start ---------------------

@router.post(
    "/{project_id}/analysis/start",
    status_code=status.HTTP_201_CREATED,
)
async def start_analysis(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """启动一轮检测。前置校验不通过 → 400 / 409;analyzing 态 → 409。"""
    project = await _fetch_visible_project(session, user, project_id)

    # 1) project.status 检查
    if project.status == "analyzing":
        # 409 — 幂等:返回当前 version + started_at
        current_version, started_at = await _get_current_version_and_start(
            session, project_id
        )
        resp = AnalysisStartConflictResponse(
            current_version=current_version or 0,
            started_at=started_at,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=resp.model_dump(mode="json"),
        )

    if project.status not in _PROJECT_START_ALLOWED:
        if project.status in ("draft", "parsing"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "项目未就绪")
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"项目状态 {project.status} 不允许启动检测"
        )

    # 2) 加载 bidders 并校验
    bidder_rows = (
        await session.execute(
            select(Bidder)
            .where(Bidder.project_id == project_id, Bidder.deleted_at.is_(None))
            .order_by(Bidder.id.asc())
        )
    ).scalars().all()

    if len(bidder_rows) < 2:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "至少需要2个投标人"
        )

    non_terminal = [
        b for b in bidder_rows if b.parse_status not in _BIDDER_TERMINAL_STATES
    ]
    if non_terminal:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "请等待所有文件解析完成"
        )

    # 3) 分配 version
    max_version = (
        await session.execute(
            select(func.coalesce(func.max(AgentTask.version), 0))
            .where(AgentTask.project_id == project_id)
        )
    ).scalar() or 0
    version = int(max_version) + 1

    # 4) 批量 INSERT AgentTask 行:C(n,2) × 7 pair + 3 global
    pair_agents = [spec for spec in AGENT_REGISTRY.values() if spec.agent_type == "pair"]
    global_agents = [spec for spec in AGENT_REGISTRY.values() if spec.agent_type == "global"]

    new_tasks: list[AgentTask] = []
    for bidder_a, bidder_b in itertools.combinations(bidder_rows, 2):
        for spec in pair_agents:
            new_tasks.append(
                AgentTask(
                    project_id=project_id,
                    version=version,
                    agent_name=spec.name,
                    agent_type="pair",
                    pair_bidder_a_id=bidder_a.id,
                    pair_bidder_b_id=bidder_b.id,
                    status="pending",
                )
            )
    for spec in global_agents:
        new_tasks.append(
            AgentTask(
                project_id=project_id,
                version=version,
                agent_name=spec.name,
                agent_type="global",
                pair_bidder_a_id=None,
                pair_bidder_b_id=None,
                status="pending",
            )
        )
    session.add_all(new_tasks)

    # 5) UPDATE project.status = analyzing
    project.status = "analyzing"
    await session.commit()

    # 6) 异步调度(INFRA_DISABLE_DETECT=1 测试时跳过)
    if not detect_disabled():
        asyncio.create_task(run_detection(project_id, version))
    else:
        logger.info(
            "detect: INFRA_DISABLE_DETECT=1, skip run_detection (project=%s v=%s)",
            project_id,
            version,
        )

    return AnalysisStartResponse(
        version=version, agent_task_count=len(new_tasks)
    )


async def _get_current_version_and_start(
    session: AsyncSession, project_id: int
) -> tuple[int | None, datetime | None]:
    row = (
        await session.execute(
            select(
                AgentTask.version,
                func.min(AgentTask.started_at),
                func.min(AgentTask.created_at),
            )
            .where(AgentTask.project_id == project_id)
            .group_by(AgentTask.version)
            .order_by(AgentTask.version.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None, None
    version, started_min, created_min = row
    return int(version), started_min or created_min


# --------------------- GET /analysis/status ---------------------

@router.get(
    "/{project_id}/analysis/status",
    response_model=AnalysisStatusResponse,
)
async def get_analysis_status(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalysisStatusResponse:
    project = await _fetch_visible_project(session, user, project_id)

    version, started_at = await _get_current_version_and_start(session, project_id)
    if version is None:
        return AnalysisStatusResponse(
            version=None,
            project_status=project.status,
            started_at=None,
            agent_tasks=[],
        )

    task_rows = (
        await session.execute(
            select(AgentTask)
            .where(
                AgentTask.project_id == project_id,
                AgentTask.version == version,
            )
            .order_by(AgentTask.id.asc())
        )
    ).scalars().all()

    return AnalysisStatusResponse(
        version=version,
        project_status=project.status,
        started_at=started_at,
        agent_tasks=[AgentTaskResponse.model_validate(t) for t in task_rows],
    )


# --------------------- GET /analysis/events (SSE) ---------------------

def _format_sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _build_status_snapshot(
    session: AsyncSession, project_id: int
) -> dict:
    version, started_at = await _get_current_version_and_start(session, project_id)
    project = (
        await session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one()
    if version is None:
        return {
            "version": None,
            "project_status": project.status,
            "started_at": None,
            "agent_tasks": [],
        }
    task_rows = (
        await session.execute(
            select(AgentTask)
            .where(
                AgentTask.project_id == project_id,
                AgentTask.version == version,
            )
            .order_by(AgentTask.id.asc())
        )
    ).scalars().all()
    return {
        "version": version,
        "project_status": project.status,
        "started_at": started_at.isoformat() if started_at else None,
        "agent_tasks": [
            {
                "id": t.id,
                "agent_name": t.agent_name,
                "agent_type": t.agent_type,
                "pair_bidder_a_id": t.pair_bidder_a_id,
                "pair_bidder_b_id": t.pair_bidder_b_id,
                "status": t.status,
                "score": float(t.score) if t.score is not None else None,
                "summary": t.summary,
                "elapsed_ms": t.elapsed_ms,
            }
            for t in task_rows
        ],
    }


async def _event_stream(request: Request, project_id: int):
    """SSE 主循环:首帧 snapshot → 订阅 broker → 超时推 heartbeat。"""
    from app.db.session import async_session

    try:
        async with async_session() as session:
            snapshot = await _build_status_snapshot(session, project_id)
        yield _format_sse("snapshot", snapshot)

        queue = progress_broker.subscribe(project_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=HEARTBEAT_INTERVAL_S
                    )
                    # C6 只转发 agent_status / report_ready;parse 阶段事件也会经过此 broker,
                    # 但 C6 不关心(前端订阅 parse-progress 端点即可),这里仍然转发供统一消费
                    yield _format_sse(event.event_type, event.data)
                except asyncio.TimeoutError:
                    ts = datetime.now(timezone.utc).isoformat()
                    yield _format_sse("heartbeat", {"ts": ts})
        finally:
            progress_broker.unsubscribe(project_id, queue)
    except asyncio.CancelledError:
        logger.info("detect SSE client disconnected project=%d", project_id)
        raise


@router.get("/{project_id}/analysis/events")
async def get_analysis_events(
    project_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
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
