"""AgentTask 模型 (C6 detect-framework)

每条 = 一轮检测里的一个 Agent 任务;pair 型两两配对,global 型全局。
字段来源:openspec/changes/detect-framework/specs/detect-framework/spec.md
"AgentTask 数据模型" Requirement + design.md D2/D3。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 6 态枚举,应用层校验(与 C3/C4 status 决策一致,不入 DB CHECK 保持跨库可移植)
AGENT_TASK_STATUSES = frozenset(
    {"pending", "running", "succeeded", "failed", "timeout", "skipped"}
)
AGENT_TYPES = frozenset({"pair", "global"})


class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(16), nullable=False)
    pair_bidder_a_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("bidders.id"), nullable=True
    )
    pair_bidder_b_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("bidders.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending", default="pending"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_agent_tasks_project_version", "project_id", "version"),
        Index("ix_agent_tasks_status_started", "status", "started_at"),
        # PostgreSQL CHECK:pair 型必须有两个 bidder,global 型必须都为 NULL
        # SQLite 环境下此约束不生效,应用层在 create_agent_task_rows 时保证
        CheckConstraint(
            "(agent_type = 'pair' "
            "AND pair_bidder_a_id IS NOT NULL "
            "AND pair_bidder_b_id IS NOT NULL) "
            "OR (agent_type = 'global' "
            "AND pair_bidder_a_id IS NULL "
            "AND pair_bidder_b_id IS NULL)",
            name="ck_agent_tasks_pair_bidder_consistency",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<AgentTask id={self.id} project={self.project_id} "
            f"v={self.version} name={self.agent_name} "
            f"type={self.agent_type} status={self.status}>"
        )


__all__ = ["AgentTask", "AGENT_TASK_STATUSES", "AGENT_TYPES"]
