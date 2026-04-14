"""启动时扫描 stuck async_tasks 并回滚实体状态 (C6 detect-framework D3)

调用时机:FastAPI lifespan startup;阻塞直至完成。

扫描条件:`status='running' AND heartbeat_at < now() - stuck_threshold`。
回滚策略(D3 只扫不自动重调):
- `extract`       → bidder.parse_status extracting → failed
- `content_parse` → bid_document.parse_status identifying → identify_failed + 聚合 bidder
- `llm_classify`  → bidder.parse_status identifying → identify_failed
- `agent_run`     → agent_tasks.status running → timeout + 若项目所有 AgentTask 终态 → project.status analyzing → ready

标 async_tasks.status='timeout' 并写 finished_at。
单 handler 失败不影响其他行(每行独立 try)。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.async_task import AsyncTask
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.project import Project

logger = logging.getLogger(__name__)


def _stuck_threshold_s() -> int:
    try:
        return int(os.environ.get("ASYNC_TASK_STUCK_THRESHOLD_S", "60"))
    except ValueError:
        return 60


def _max_scan_rows() -> int:
    try:
        return int(os.environ.get("ASYNC_TASK_MAX_SCAN_ROWS", "1000"))
    except ValueError:
        return 1000


async def scan_and_recover() -> dict[str, int]:
    """主入口:扫 stuck 行 + 分派 handler。返回各 subtype 恢复计数(含 error)。"""
    counts = {
        "extract": 0,
        "content_parse": 0,
        "llm_classify": 0,
        "agent_run": 0,
        "error": 0,
    }

    threshold = datetime.now(timezone.utc) - timedelta(seconds=_stuck_threshold_s())
    max_rows = _max_scan_rows()

    async with async_session() as session:
        stmt = (
            select(AsyncTask)
            .where(
                AsyncTask.status == "running",
                AsyncTask.heartbeat_at < threshold,
            )
            .limit(max_rows)
        )
        stuck_rows = list((await session.execute(stmt)).scalars().all())

        for task in stuck_rows:
            try:
                if task.subtype == "extract":
                    await _recover_extract(session, task)
                elif task.subtype == "content_parse":
                    await _recover_content_parse(session, task)
                elif task.subtype == "llm_classify":
                    await _recover_llm_classify(session, task)
                elif task.subtype == "agent_run":
                    await _recover_agent_run(session, task)
                else:
                    logger.warning(
                        "scanner: unknown subtype=%s task_id=%s",
                        task.subtype,
                        task.id,
                    )

                # 标 async_tasks 为 timeout
                task.status = "timeout"
                task.finished_at = datetime.now(timezone.utc)
                if not task.error:
                    task.error = "系统重启期间心跳过期,已回滚"
                counts[task.subtype] = counts.get(task.subtype, 0) + 1
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "scanner: handler crash task=%s subtype=%s: %s",
                    task.id,
                    task.subtype,
                    exc,
                )
                counts["error"] += 1

        await session.commit()

    logger.info(
        "scanner: %d extract, %d content_parse, %d llm_classify, %d agent_run, %d errors",
        counts["extract"],
        counts["content_parse"],
        counts["llm_classify"],
        counts["agent_run"],
        counts["error"],
    )
    return counts


# ------------------ handlers ------------------

async def _recover_extract(session: AsyncSession, task: AsyncTask) -> None:
    """C4 extract stuck → bidder.parse_status extracting → failed。"""
    bidder = await session.get(Bidder, task.entity_id)
    if bidder is None:
        return
    if bidder.parse_status == "extracting":
        bidder.parse_status = "failed"
        bidder.parse_error = "系统重启导致解压任务中断,请重试"
        bidder.updated_at = datetime.now(timezone.utc)


async def _recover_content_parse(session: AsyncSession, task: AsyncTask) -> None:
    """C5 content_parse stuck → bid_document.parse_status identifying → identify_failed。"""
    doc = await session.get(BidDocument, task.entity_id)
    if doc is None:
        return
    if doc.parse_status == "identifying":
        doc.parse_status = "identify_failed"
        doc.parse_error = "系统重启导致内容提取任务中断,请重试"


async def _recover_llm_classify(session: AsyncSession, task: AsyncTask) -> None:
    """C5 llm_classify stuck → bidder.parse_status identifying → identify_failed。"""
    bidder = await session.get(Bidder, task.entity_id)
    if bidder is None:
        return
    if bidder.parse_status == "identifying":
        bidder.parse_status = "identify_failed"
        bidder.parse_error = "系统重启导致 LLM 分类任务中断,请重试"
        bidder.updated_at = datetime.now(timezone.utc)


async def _recover_agent_run(session: AsyncSession, task: AsyncTask) -> None:
    """C6 agent_run stuck → AgentTask running → timeout;若项目所有 AgentTask 终态 → project analyzing → ready。"""
    agent_task = await session.get(AgentTask, task.entity_id)
    if agent_task is None:
        return
    if agent_task.status == "running":
        agent_task.status = "timeout"
        agent_task.summary = "系统重启导致 Agent 任务中断"
        agent_task.finished_at = datetime.now(timezone.utc)

    # 检查该项目是否所有 AgentTask 都终态 → project 回 ready
    project_id = agent_task.project_id
    version = agent_task.version
    non_terminal_stmt = select(AgentTask.id).where(
        AgentTask.project_id == project_id,
        AgentTask.version == version,
        AgentTask.status.in_(("pending", "running")),
    )
    remaining = (await session.execute(non_terminal_stmt)).first()
    if remaining is None:
        project = await session.get(Project, project_id)
        if project is not None and project.status == "analyzing":
            project.status = "ready"


__all__ = ["scan_and_recover"]
