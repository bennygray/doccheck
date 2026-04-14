"""BidDocument 模型 (C4 file-upload)

每条记录 = 解压后的一个文件(或被跳过/失败的占位)。
依附 bidder 生命周期:bidder 软删时此表硬删(D1)。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BidDocument(Base):
    __tablename__ = "bid_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bidder_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bidders.id"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # ".docx" / ".xlsx" / ".jpg" / ...
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    md5: Mapped[str] = mapped_column(String(32), nullable=False)
    # C5 LLM 填:营业执照 / 报价表 / 投标函 / ...;C4 阶段恒为 NULL
    file_role: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
    # C5 新增:high / low / user / NULL;低置信度前端黄色徽章
    role_confidence: Mapped[str | None] = mapped_column(
        String(16), nullable=True, default=None
    )
    parse_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending", default="pending"
    )
    parse_error: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None
    )
    # 原压缩包文件名(标识此文件来自哪个压缩包,便于追加上传时区分)
    source_archive: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # MD5 去重粒度 = 投标人内(D8 决策)
        UniqueConstraint("bidder_id", "md5", name="uq_bid_documents_bidder_md5"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<BidDocument id={self.id} bidder={self.bidder_id} "
            f"name={self.file_name!r} status={self.parse_status}>"
        )


__all__ = ["BidDocument"]
