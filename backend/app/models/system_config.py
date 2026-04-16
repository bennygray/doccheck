"""SystemConfig 模型 (C17 admin-users)

全局检测规则配置，单行存储（id=1）。
config 字段为完整 JSON 对象，结构见 requirements.md §8。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# JSONB 在 SQLite 单测下降级为 JSON；Postgres 仍走 JSONB
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


class SystemConfig(Base):
    __tablename__ = "system_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config: Mapped[dict] = mapped_column(_JSONB_OR_JSON, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
