"""PriceParsingRule 模型 (C4 骨架 + C5 LLM 填充)

1 项目 → 多 sheet 规则。C4 阶段端点骨架就位(GET/PUT),L2 用 fixture INSERT
直接验证 round-trip;C5 由 LLM 调用 PUT 写入。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# JSONB 在 SQLite 单测下降级为 JSON;Postgres 仍走 JSONB
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")

from app.db.base import Base

# column_mapping JSONB 的必需键(C5 LLM 输出契约;PUT 时校验)
REQUIRED_MAPPING_KEYS = frozenset(
    {"code_col", "name_col", "unit_col", "qty_col",
     "unit_price_col", "total_price_col"}
)


class PriceParsingRule(Base):
    __tablename__ = "price_parsing_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False
    )
    sheet_name: Mapped[str] = mapped_column(String(200), nullable=False)
    header_row: Mapped[int] = mapped_column(Integer, nullable=False)
    column_mapping: Mapped[dict[str, Any]] = mapped_column(
        _JSONB_OR_JSON, nullable=False
    )
    # C5 新增:identifying | confirmed | failed;支撑 rule_coordinator 原子占位
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="identifying",
        default="identifying",
    )
    created_by_llm: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_price_rules_project_sheet", "project_id", "sheet_name"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<PriceParsingRule id={self.id} project={self.project_id} "
            f"sheet={self.sheet_name!r}>"
        )


__all__ = ["PriceParsingRule", "REQUIRED_MAPPING_KEYS"]
