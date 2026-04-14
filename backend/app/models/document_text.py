"""DocumentText 模型 (C5 parser-pipeline US-4.2)

每条记录 = DOCX 段落 / 页眉 / 页脚 / 文本框 / 表格行 / XLSX sheet 合并文本之一。
location 区分来源,页眉页脚不参与相似度(US-4.2 AC-3)。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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

# location 枚举(应用层校验,不加 DB CHECK)
LOCATION_VALUES = frozenset(
    {"body", "header", "footer", "textbox", "table_row", "sheet"}
)


class DocumentText(Base):
    __tablename__ = "document_texts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bid_document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bid_documents.id"), nullable=False
    )
    paragraph_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # body | header | footer | textbox | table_row | sheet
    location: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_document_texts_doc_idx",
            "bid_document_id",
            "paragraph_index",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<DocumentText id={self.id} doc={self.bid_document_id} "
            f"idx={self.paragraph_index} loc={self.location}>"
        )


__all__ = ["DocumentText", "LOCATION_VALUES"]
