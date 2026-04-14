"""DocumentSheet 模型 (C9 detect-agent-structure-similarity)

每条记录 = XLSX 文件中一个 sheet 的整表 cell 矩阵 + 合并单元格信息。
供 C9 structure_similarity Agent 的字段结构/表单填充模式维度消费。

与 DocumentText.location='sheet' 的合并文本双写:
- DocumentText(相似度 Agent 用)
- DocumentSheet(结构维度 Agent 用)
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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# PG 用 JSONB,SQLite 测试用 JSON
JSON_VARIANT = JSON().with_variant(JSONB(), "postgresql")


class DocumentSheet(Base):
    __tablename__ = "document_sheets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bid_document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bid_documents.id"), nullable=False
    )
    # workbook 中 0-based sheet 顺序
    sheet_index: Mapped[int] = mapped_column(Integer, nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # [[cell, cell, ...], ...] cell = str | int | float | bool | None
    # 上限 STRUCTURE_SIM_MAX_ROWS_PER_SHEET 行,超出截断
    rows_json: Mapped[list[list[Any]]] = mapped_column(
        JSON_VARIANT, nullable=False
    )
    # openpyxl ws.merged_cells.ranges 字符串化,如 ["A1:B2", "C3:D4"]
    merged_cells_json: Mapped[list[str]] = mapped_column(
        JSON_VARIANT, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "bid_document_id", "sheet_index", name="uq_document_sheets_doc_idx"
        ),
        Index("ix_document_sheets_doc", "bid_document_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<DocumentSheet id={self.id} doc={self.bid_document_id} "
            f"idx={self.sheet_index} name={self.sheet_name!r}>"
        )


__all__ = ["DocumentSheet", "JSON_VARIANT"]
