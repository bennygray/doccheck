"""ExportTemplate 模型 (C15 report-export,骨架预留)

用户上传 Word 模板的 DB 表。本 change 只建表,不暴露 upload endpoint。
admin 可手工 INSERT(或后续 follow-up change 加上传 UI)。

字段来源:openspec/changes/report-export/design.md D7 + tasks 1.3。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExportTemplate(Base):
    __tablename__ = "export_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<ExportTemplate id={self.id} owner={self.owner_id} name={self.name!r}>"


__all__ = ["ExportTemplate"]
