"""项目状态自动流转 (DEF-001 fix)

解析流水线完成后检查同项目所有 bidder 是否均为终态,
若是则将 project.status 从 draft/parsing 流转到 ready。

用 SELECT ... FOR UPDATE 行锁防止并发竞态。
"""

from __future__ import annotations

import logging

from sqlalchemy import select, update

from app.db.session import async_session
from app.models.bidder import Bidder
from app.models.project import Project
from app.services.parser.pipeline.progress_broker import progress_broker

logger = logging.getLogger(__name__)

# bidder 终态集合
_BIDDER_TERMINAL_STATUSES = frozenset({
    "identified",
    "priced",
    "price_partial",
    "partial",
    "identify_failed",
    "price_failed",
    "needs_password",
    "failed",
    "skipped",
})

# 允许流转到 ready 的源状态
_TRANSITION_FROM = frozenset({"draft", "parsing"})


async def try_transition_project_ready(project_id: int) -> bool:
    """检查项目所有 bidder 是否均为终态,若是则流转到 ready。

    Returns:
        True 如果本次调用触发了 project.status → ready 的更新。
    """
    async with async_session() as session:
        # 行锁 project 防并发
        project = (
            await session.execute(
                select(Project)
                .where(Project.id == project_id)
                .with_for_update()
            )
        ).scalar_one_or_none()

        if project is None:
            return False

        if project.status not in _TRANSITION_FROM:
            return False

        # 查询同项目所有 bidder 的 parse_status
        bidders = (
            await session.execute(
                select(Bidder.parse_status).where(
                    Bidder.project_id == project_id,
                    Bidder.deleted_at.is_(None),
                )
            )
        ).scalars().all()

        if not bidders:
            return False

        if not all(s in _BIDDER_TERMINAL_STATUSES for s in bidders):
            return False

        project.status = "ready"
        await session.commit()

    logger.info("project %d status -> ready (all bidders terminal)", project_id)

    await progress_broker.publish(
        project_id,
        "project_status_changed",
        {"new_status": "ready"},
    )
    return True


async def try_transition_project_parsing(project_id: int) -> bool:
    """上传触发解析时,将 project.status 从 draft 流转到 parsing。

    Returns:
        True 如果本次调用触发了更新。
    """
    async with async_session() as session:
        result = await session.execute(
            update(Project)
            .where(Project.id == project_id)
            .where(Project.status == "draft")
            .values(status="parsing")
        )
        await session.commit()
        updated = result.rowcount > 0  # type: ignore[union-attr]

    if updated:
        logger.info("project %d status -> parsing", project_id)
        await progress_broker.publish(
            project_id,
            "project_status_changed",
            {"new_status": "parsing"},
        )
    return updated
