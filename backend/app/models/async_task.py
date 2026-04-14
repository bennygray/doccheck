"""AsyncTask 模型 (C6 detect-framework, D3 决策)

通用异步任务追踪表,4 subtype 覆盖 C4 extract / C5 content_parse + llm_classify / C6 agent_run。
启动时 scanner 扫 heartbeat_at 过期的 running 行,触发回滚 handler(不自动重调)。
字段来源:design.md D1 / D6 + spec "async_tasks 通用任务表与重启恢复"。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 4 subtype + 4 态,应用层校验
ASYNC_TASK_SUBTYPES = frozenset(
    {"extract", "content_parse", "llm_classify", "agent_run"}
)
ASYNC_TASK_STATUSES = frozenset({"running", "done", "timeout", "failed"})


class AsyncTask(Base):
    __tablename__ = "async_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subtype: Mapped[str] = mapped_column(String(32), nullable=False)
    # 不加 FK:4 种 entity_type 指向不同表,统一靠业务层映射
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="running", default="running"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_async_tasks_status_heartbeat", "status", "heartbeat_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<AsyncTask id={self.id} subtype={self.subtype} "
            f"entity={self.entity_type}:{self.entity_id} status={self.status}>"
        )


__all__ = ["AsyncTask", "ASYNC_TASK_SUBTYPES", "ASYNC_TASK_STATUSES"]
