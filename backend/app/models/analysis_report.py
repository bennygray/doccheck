"""AnalysisReport 模型 (C6 detect-framework)

一次检测的综合研判产物;行存在 = 检测完成。
UNIQUE(project_id, version) 保证同项目同 version 仅一条。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 风险等级 3 态,应用层校验
RISK_LEVELS = frozenset({"high", "medium", "low"})


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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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


__all__ = ["AnalysisReport", "RISK_LEVELS"]
