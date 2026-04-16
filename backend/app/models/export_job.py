"""ExportJob 模型 (C15 report-export)

Word 导出作业独立表(B2 决策,不复用 AsyncTask)。
状态机:pending → running → succeeded | failed。
文件落盘 uploads/exports/{id}.docx;7 天过期 cleanup 置 file_expired=true 但保留行。

字段来源:openspec/changes/report-export/specs/report-export/spec.md "export_jobs 表结构"。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 4 态枚举,应用层校验
EXPORT_JOB_STATUSES = frozenset({"pending", "running", "succeeded", "failed"})


class ExportJob(Base):
    __tablename__ = "export_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False
    )
    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("analysis_reports.id"), nullable=False
    )
    actor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    template_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("export_templates.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending", default="pending"
    )
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="0", default=False
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_expired: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="0", default=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_export_jobs_project_created", "project_id", "created_at"),
        Index("ix_export_jobs_report_created", "report_id", "created_at"),
        Index("ix_export_jobs_status_finished", "status", "finished_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<ExportJob id={self.id} report={self.report_id} "
            f"status={self.status} fallback={self.fallback_used}>"
        )


__all__ = ["ExportJob", "EXPORT_JOB_STATUSES"]
