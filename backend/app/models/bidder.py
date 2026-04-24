"""Bidder 模型 (C4 file-upload)

字段对齐 openspec/changes/file-upload/specs/file-upload/spec.md "数据模型字段"
与 design.md D1(软删 + 文件硬删)。

权限过滤复用 C3 模式:bidder 通过 project_id 挂在 Project 上,可见性
等同于"宿主项目可见"。`get_visible_bidders_stmt` 是 `get_visible_projects_stmt`
的下钻 helper,所有读取路径 MUST 经此函数。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import Select

# JSONB 在 SQLite 单测下需要降级为 JSON;Postgres 仍走 JSONB 索引
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")

from app.db.base import Base
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User

# 解析状态枚举(应用层校验,不入 DB CHECK,与 C3 status 决策一致)
PARSE_STATUSES = frozenset(
    {"pending", "extracting", "extracted", "skipped", "partial",
     "failed", "needs_password"}
)


class Bidder(Base):
    __tablename__ = "bidders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), nullable=False
    )
    parse_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending", default="pending"
    )
    parse_error: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None
    )
    file_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    # C5 LLM 填:身份证 / 营业执照 / 法人 / ...
    identity_info: Mapped[dict[str, Any] | None] = mapped_column(
        _JSONB_OR_JSON, nullable=True, default=None
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
    # 软删除:与 C3 Project 一致;关联 bid_documents 在删除时硬删(D1)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    __table_args__ = (
        Index("ix_bidders_project_deleted", "project_id", "deleted_at"),
        # 同项目内活跃投标人 name 唯一(软删后释放 name 空间)
        # 用 partial unique index 而非 UniqueConstraint:PG 中
        # NULL != NULL,普通 UniqueConstraint 无法防止 (pid, name, NULL) 重复。
        Index(
            "uq_bidders_project_name_alive",
            "project_id", "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    @property
    def identity_info_status(self) -> str:
        """honest-detection-results F3: 身份信息充分性状态。

        用于前端 UI / Word 导出对"LLM 没抽出身份信息"场景显式降级文案。
        None 或空 dict 都算 insufficient;非空 dict(即使只含 company_name)算 sufficient。
        """
        return "sufficient" if self.identity_info else "insufficient"

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<Bidder id={self.id} name={self.name!r} "
            f"project={self.project_id} status={self.parse_status} "
            f"deleted={self.deleted_at is not None}>"
        )


def get_visible_bidders_stmt(
    current_user: User,
    project_id: int | None = None,
    include_deleted: bool = False,
) -> Select[tuple[Bidder]]:
    """返回已应用项目级权限过滤 + 软删过滤的 ``SELECT`` 语句。

    - 通过 JOIN projects 复用 C3 `get_visible_projects_stmt` 的过滤逻辑
    - reviewer 只能看到自己项目下的投标人;admin 不限
    - 默认过滤 bidders.deleted_at IS NULL(被软删投标人不返回)
    - 默认过滤宿主项目的 deleted_at IS NULL(项目软删 → 投标人也不可见)
    """
    visible_projects = get_visible_projects_stmt(current_user).subquery()
    stmt: Select[tuple[Bidder]] = (
        select(Bidder)
        .join(visible_projects, Bidder.project_id == visible_projects.c.id)
    )
    if not include_deleted:
        stmt = stmt.where(Bidder.deleted_at.is_(None))
    if project_id is not None:
        stmt = stmt.where(Bidder.project_id == project_id)
    return stmt


__all__ = ["Bidder", "PARSE_STATUSES", "get_visible_bidders_stmt"]
