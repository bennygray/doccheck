"""数据生命周期 dry-run 清理 - C1 infra-base

C1 阶段强制 dry-run:仅扫描过期文件并输出清单到日志,**不真实删除**。
真删功能随 C4 `file-upload` 一起开放(届时把 LIFECYCLE_DRY_RUN 开关放开)。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


def scan_expired(root: str | Path, age_days: int) -> list[Path]:
    """扫描 root 下修改时间超过 age_days 的文件,仅返回清单,不删。

    - 不存在的 root 返回空清单,不报错
    - 递归扫描子目录
    - 只统计普通文件,跳过目录与符号链接
    """
    root_path = Path(root)
    if not root_path.exists():
        return []

    cutoff = time.time() - age_days * 86400
    expired: list[Path] = []
    for path in root_path.rglob("*"):
        try:
            if not path.is_file():
                continue
            if path.is_symlink():
                continue
            if path.stat().st_mtime < cutoff:
                expired.append(path)
        except OSError as exc:  # 权限、竞态等
            logger.warning("scan_expired: skip %s (%s)", path, exc)
    return expired


class LifecycleTask:
    """后台定时任务:周期性 scan_expired,输出清单到日志。

    C1 阶段强制 dry_run=True,不真实删除。
    """

    def __init__(self) -> None:
        self._running = False

    async def _run(self) -> None:
        self._running = True
        logger.info(
            "lifecycle task started (dry_run=%s, interval=%ss, age_days=%s, root=%s)",
            settings.lifecycle_dry_run,
            settings.lifecycle_interval_s,
            settings.lifecycle_age_days,
            settings.upload_dir,
        )
        while self._running:
            try:
                expired = scan_expired(
                    settings.upload_dir, settings.lifecycle_age_days
                )
                if expired:
                    logger.info(
                        "lifecycle dry-run: %d expired files found (NOT deleted)",
                        len(expired),
                    )
                    for p in expired[:50]:  # 限量避免日志洪水
                        logger.info("  - %s", p)
                else:
                    logger.debug("lifecycle dry-run: no expired files")
            except Exception as exc:  # noqa: BLE001
                logger.exception("lifecycle scan failed: %s", exc)

            try:
                await asyncio.sleep(settings.lifecycle_interval_s)
            except asyncio.CancelledError:
                break
        logger.info("lifecycle task stopped")

    def start(self) -> asyncio.Task[None]:
        return asyncio.create_task(self._run(), name="lifecycle-cleanup")

    async def stop(self, task: asyncio.Task[None]) -> None:
        self._running = False
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


lifecycle_task = LifecycleTask()
