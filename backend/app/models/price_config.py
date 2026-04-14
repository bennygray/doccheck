"""ProjectPriceConfig 模型 (C4 file-upload, US-4.4)

1:1 与 Project 关联:project_id 同时是 PK + FK。
项目创建时不自动 INSERT 默认配置(D9);首次 GET 返 null,前端引导配置。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 应用层枚举(与 schemas 共享)
CURRENCIES = frozenset({"CNY", "USD", "EUR", "HKD"})
UNIT_SCALES = frozenset({"yuan", "wan_yuan", "fen"})


class ProjectPriceConfig(Base):
    __tablename__ = "project_price_configs"

    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), primary_key=True
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    tax_inclusive: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unit_scale: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<ProjectPriceConfig project={self.project_id} "
            f"currency={self.currency} unit={self.unit_scale} "
            f"tax_inclusive={self.tax_inclusive}>"
        )


__all__ = ["ProjectPriceConfig", "CURRENCIES", "UNIT_SCALES"]
