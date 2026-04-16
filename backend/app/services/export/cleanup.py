"""7 天过期文件清理 (C15 report-export, D5)

run_once(now=None) 扫 export_jobs WHERE status='succeeded' AND finished_at < NOW - 7d
AND file_expired=false → rm file + UPDATE file_expired=true。
单个 job 清理失败(FileNotFoundError / PermissionError / 其他)不中断其他 job。

ExportCleanupTask 为后台周期任务(lifespan 启动/关闭);默认每日 02:00 触发
一次,测试环境可用 INFRA_DISABLE_EXPORT_CLEANUP=1 关闭。
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, update

from app.db.session import async_session
from app.models.export_job import ExportJob

logger = logging.getLogger(__name__)

EXPIRE_DAYS = 7


async def run_once(now: datetime | None = None) -> dict:
    """执行一次清理;返回统计 {scanned, rm_ok, rm_err}。"""
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=EXPIRE_DAYS)

    stats = {"scanned": 0, "rm_ok": 0, "rm_err": 0}
    async with async_session() as session:
        rows = (
            await session.execute(
                select(ExportJob).where(
                    ExportJob.status == "succeeded",
                    ExportJob.finished_at < cutoff,
                    ExportJob.file_expired.is_(False),
                )
            )
        ).scalars().all()
        stats["scanned"] = len(rows)
        for job in rows:
            try:
                if job.file_path:
                    p = Path(job.file_path)
                    if p.exists():
                        os.remove(p)
                stats["rm_ok"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "cleanup rm failed job=%s path=%s err=%s",
                    job.id,
                    job.file_path,
                    exc,
                )
                stats["rm_err"] += 1
            # 无论 rm 成功与否,都标记 expired(磁盘可能被人工删除;
            # 我们关心的是 DB 态与 downloadability)
            await session.execute(
                update(ExportJob)
                .where(ExportJob.id == job.id)
                .values(file_expired=True)
            )
        await session.commit()

    return stats


def _seconds_until_next_0200(now: datetime | None = None) -> float:
    """返回距离下一个凌晨 02:00 的秒数。"""
    if now is None:
        now = datetime.now(timezone.utc).astimezone()
    target = now.replace(hour=2, minute=0, second=0, microsecond=0)
    if now >= target:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


class ExportCleanupTask:
    """后台每日 02:00 触发 cleanup.run_once。简化实现,不引入 APScheduler。"""

    def __init__(self) -> None:
        self._running = False

    async def _run(self) -> None:
        self._running = True
        logger.info("export cleanup task started")
        while self._running:
            try:
                await asyncio.sleep(_seconds_until_next_0200())
            except asyncio.CancelledError:
                break
            if not self._running:
                break
            try:
                stats = await run_once()
                logger.info("export cleanup: %s", stats)
            except Exception as exc:  # noqa: BLE001
                logger.exception("export cleanup failed: %s", exc)
        logger.info("export cleanup task stopped")

    def start(self) -> asyncio.Task[None]:
        return asyncio.create_task(self._run(), name="export-cleanup")

    async def stop(self, task: asyncio.Task[None]) -> None:
        self._running = False
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


export_cleanup_task = ExportCleanupTask()


__all__ = ["run_once", "EXPIRE_DAYS", "ExportCleanupTask", "export_cleanup_task"]
