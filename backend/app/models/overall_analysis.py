"""OverallAnalysis 模型 (C6 detect-framework)

global 型 Agent 的全局分析结果(错误一致性 / 语言风格 / 图片复用)。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


class OverallAnalysis(Base):
    __tablename__ = "overall_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSONB_OR_JSON, nullable=True, default=None
    )
    # C15 维度级人工复核标记(null = 未复核;schema: {action, comment, reviewer_id, at})
    manual_review_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSONB_OR_JSON, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_overall_analyses_project_version_dim",
            "project_id",
            "version",
            "dimension",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<OverallAnalysis id={self.id} project={self.project_id} "
            f"v={self.version} dim={self.dimension} score={self.score}>"
        )


__all__ = ["OverallAnalysis"]
