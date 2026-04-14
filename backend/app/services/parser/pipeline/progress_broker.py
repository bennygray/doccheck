"""项目级 SSE 事件 Broker (C5 parser-pipeline B1 / D6)

单进程内存 broker:`dict[project_id, list[asyncio.Queue]]`。
- pipeline 协程 `publish(project_id, event_type, data)` 推事件
- SSE 端点 `subscribe(project_id)` 拿 queue,循环 await queue.get() 推给客户端
- 客户端断开 → unsubscribe 摘除 queue

多 worker 部署升级留 C17+(Redis pub/sub)。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProgressEvent:
    event_type: str  # bidder_status_changed / document_role_classified / ...
    data: dict[str, Any]


@dataclass
class ProgressBroker:
    # project_id → 订阅者 queue 列表
    _subscribers: dict[int, list[asyncio.Queue]] = field(default_factory=dict)

    def subscribe(self, project_id: int) -> asyncio.Queue:
        """新订阅者。返回 queue(订阅者循环 await queue.get())。"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.setdefault(project_id, []).append(queue)
        return queue

    def unsubscribe(self, project_id: int, queue: asyncio.Queue) -> None:
        """客户端断开时清理。即使 queue 不在列表中也不抛错。"""
        lst = self._subscribers.get(project_id)
        if not lst:
            return
        try:
            lst.remove(queue)
        except ValueError:
            pass
        if not lst:
            self._subscribers.pop(project_id, None)

    async def publish(
        self, project_id: int, event_type: str, data: dict[str, Any]
    ) -> None:
        """异步推事件到所有订阅者。queue 满时丢弃该订阅者的这条事件(非阻塞)。"""
        lst = self._subscribers.get(project_id)
        if not lst:
            return
        event = ProgressEvent(event_type=event_type, data=data)
        for queue in lst:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "progress_broker queue full, dropping event %s for project %d",
                    event_type,
                    project_id,
                )

    def subscriber_count(self, project_id: int) -> int:
        return len(self._subscribers.get(project_id, []))


# 模块级单例
progress_broker = ProgressBroker()


__all__ = ["ProgressBroker", "ProgressEvent", "progress_broker"]
