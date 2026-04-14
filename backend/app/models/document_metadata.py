"""DocumentMetadata 模型 (C5 parser-pipeline US-4.2)

1:1 关联 bid_document,存 docProps/core.xml + app.xml 抽出的元信息。
所有字段可空(值缺失写 NULL 不抛错)。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentMetadata(Base):
    __tablename__ = "document_metadata"

    # 1:1 复用 bid_document.id 作为 PK(与 project_price_configs 同模式)
    bid_document_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("bid_documents.id"),
        primary_key=True,
    )
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_saved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    doc_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    doc_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    app_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    template: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<DocumentMetadata doc={self.bid_document_id} "
            f"author={self.author!r}>"
        )


__all__ = ["DocumentMetadata"]
