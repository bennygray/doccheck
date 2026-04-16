"""AuditLog 模型 (C15 report-export)

用户操作审计日志:独立表,与 AgentTask(检测执行日志)/ AsyncTask(异步任务追踪)正交。
写入放事务外 try/except,失败不影响主业务(见 services/audit.py)。

字段来源:openspec/changes/report-export/specs/audit-log/spec.md "audit_log 表结构"。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")

# action 白名单(应用层校验;非法抛 ValueError)
AUDIT_ACTIONS = frozenset(
    {
        # 复核类
        "review.report_confirmed",
        "review.report_rejected",
        "review.report_downgraded",
        "review.report_upgraded",
        "review.dimension_marked",
        # 导出类
        "export.requested",
        "export.succeeded",
        "export.failed",
        "export.downloaded",
        "export.fallback_to_builtin",
        # 模板类(预留)
        "template.uploaded",
    }
)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False
    )
    report_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("analysis_reports.id"), nullable=True
    )
    actor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSONB_OR_JSON, nullable=True, default=None
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSONB_OR_JSON, nullable=True, default=None
    )
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_audit_logs_project_created",
            "project_id",
            "created_at",
        ),
        Index(
            "ix_audit_logs_report_created",
            "report_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<AuditLog id={self.id} project={self.project_id} "
            f"action={self.action} actor={self.actor_id}>"
        )


__all__ = ["AuditLog", "AUDIT_ACTIONS"]
