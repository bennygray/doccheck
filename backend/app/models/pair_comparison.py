"""PairComparison 模型 (C6 detect-framework)

pair 型 Agent 的跨投标人对比结果。
字段来源:openspec/changes/detect-framework/specs/detect-framework/spec.md
"AnalysisReport 与 PairComparison / OverallAnalysis 数据模型" Requirement。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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

# JSONB 在 SQLite 单测下降级为 JSON
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


class PairComparison(Base):
    __tablename__ = "pair_comparisons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    bidder_a_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bidders.id"), nullable=False
    )
    bidder_b_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bidders.id"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(
        _JSONB_OR_JSON, nullable=True, default=None
    )
    is_ironclad: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_pair_comparisons_project_version_dim",
            "project_id",
            "version",
            "dimension",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<PairComparison id={self.id} project={self.project_id} "
            f"v={self.version} dim={self.dimension} score={self.score}>"
        )


__all__ = ["PairComparison"]
