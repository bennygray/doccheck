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
    # parser-accuracy-fixes P1-5 / H2:新权威字段 sheets_config(多 sheet 候选)
    # 数组 of {sheet_name, header_row, column_mapping};失败态 rule 为 []
    sheets_config: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSONB_OR_JSON, nullable=False, default=list
    )
    # 下面 3 列 deprecated:parser-accuracy-fixes 后由 sheets_config 取代
    # 保留做 backward compat 缓冲(老 admin UI GET 仍读这 3 列;新 rule 写入时同步回写 sheets_config[0])
    # 下个 parser change 统一清理(drop 列前确认老 UI 已切掉)
    sheet_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    header_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_mapping: Mapped[dict[str, Any] | None] = mapped_column(
        _JSONB_OR_JSON, nullable=True
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
