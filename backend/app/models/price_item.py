"""PriceItem 模型 (C5 parser-pipeline US-4.4)

每条记录 = bidder 报价表中的一行数据,按 price_parsing_rule 提取。
规则修改后 DELETE + 重回填 (D4 决策);修正前后的 PriceItem 不兼容。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PriceItem(Base):
    __tablename__ = "price_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bidder_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bidders.id"), nullable=False
    )
    price_parsing_rule_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("price_parsing_rules.id"), nullable=False
    )
    sheet_name: Mapped[str] = mapped_column(String(200), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # 规则抽取的 6 个业务字段;归一化失败写 NULL 不阻断行
    item_code: Mapped[str | None] = mapped_column(String(200), nullable=True)
    item_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_price_items_bidder_rule",
            "bidder_id",
            "price_parsing_rule_id",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<PriceItem id={self.id} bidder={self.bidder_id} "
            f"sheet={self.sheet_name!r} row={self.row_index}>"
        )


__all__ = ["PriceItem"]
