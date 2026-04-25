"""AnalysisReport 模型 (C6 detect-framework)

一次检测的综合研判产物;行存在 = 检测完成。
UNIQUE(project_id, version) 保证同项目同 version 仅一条。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# JSONB 在 SQLite 单测下降级为 JSON(与 overall_analysis / pair_comparison 同模式)
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")

# 风险等级 3 态,应用层校验
RISK_LEVELS = frozenset({"high", "medium", "low"})

# C15 人工复核 status 4 态(null = 未复核)
MANUAL_REVIEW_STATUSES = frozenset(
    {"confirmed", "rejected", "downgraded", "upgraded"}
)


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    # C6 留空;C14 接 LLM 综合研判时填
    llm_conclusion: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="", default=""
    )
    # C15 人工复核字段(整报告级,null = 未复核)
    manual_review_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, default=None
    )
    manual_review_comment: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    reviewer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, default=None
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # CH-2 detect-template-exclusion: 模板簇识别可观测性
    template_cluster_detected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        default=False,
    )
    template_cluster_adjusted_scores: Mapped[dict | None] = mapped_column(
        _JSONB_OR_JSON, nullable=True, default=None
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id", "version", name="uq_analysis_reports_project_version"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<AnalysisReport id={self.id} project={self.project_id} "
            f"v={self.version} score={self.total_score} risk={self.risk_level}>"
        )


__all__ = ["AnalysisReport", "RISK_LEVELS", "MANUAL_REVIEW_STATUSES"]
