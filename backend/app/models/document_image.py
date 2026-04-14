"""DocumentImage 模型 (C5 parser-pipeline US-4.2)

每条记录 = DOCX 嵌入图片或独立图片文件。
md5 (32 hex) + phash (64 hex) 供后续 C11+ 图片相似度检测使用。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentImage(Base):
    __tablename__ = "document_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bid_document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bid_documents.id"), nullable=False
    )
    # extracted/<pid>/<bid>/<hash>/imgs/<img_hash>.<ext>
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    md5: Mapped[str] = mapped_column(String(32), nullable=False)
    # phash 64 bit 按 16 字符 hex 存储
    phash: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # "body" / "header" / "footer" / "<sheet_name>" 等
    position: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_document_images_doc_md5", "bid_document_id", "md5"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<DocumentImage id={self.id} doc={self.bid_document_id} "
            f"md5={self.md5[:8]}>"
        )


__all__ = ["DocumentImage"]
