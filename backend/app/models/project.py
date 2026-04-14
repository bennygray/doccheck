"""Project 模型 (C3 project-mgmt)

字段来源:openspec/changes/project-mgmt/specs/project-mgmt/spec.md 的"数据模型字段" Requirement
与 design.md D1/D2/D3/D4 的决策。

软删除 + 角色过滤统一走 ``get_visible_projects_stmt``,避免在业务路径里手写 filter。
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
    select,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import Select

from app.db.base import Base
from app.models.user import User


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    bid_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None
    )
    max_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, default=None
    )
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None
    )
    # "draft" | "parsing" | "ready" | "analyzing" | "completed"
    # C3 阶段实际只产生 "draft";其他值预留给 C6+ 状态推进
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="draft", default="draft"
    )
    # C3 阶段恒为 None;C6+ 检测完成后填充
    risk_level: Mapped[str | None] = mapped_column(
        String(16), nullable=True, default=None
    )
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
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
    # 软删除标记:NULL=活跃;非 NULL=已软删,被所有查询过滤
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    __table_args__ = (
        # reviewer 列表主路径 + admin 列表排序的联合索引
        # 覆盖 WHERE owner_id=? AND deleted_at IS NULL ORDER BY created_at DESC
        Index(
            "ix_projects_owner_deleted_created",
            "owner_id",
            "deleted_at",
            "created_at",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<Project id={self.id} name={self.name!r} "
            f"owner={self.owner_id} status={self.status} "
            f"deleted={self.deleted_at is not None}>"
        )


def get_visible_projects_stmt(
    current_user: User,
    include_deleted: bool = False,
) -> Select[tuple[Project]]:
    """返回已应用软删过滤 + 角色过滤的 ``SELECT`` 语句。

    所有读取路径(list / detail / delete 前置校验)都 MUST 通过此函数,
    避免"忘加过滤"导致数据泄露(参见 design.md D1 / D2)。

    - include_deleted=False(默认)→ 过滤 deleted_at IS NULL
    - reviewer → 仅限 owner_id == current_user.id
    - admin    → 不加 owner 过滤
    """
    stmt: Select[tuple[Project]] = select(Project)
    if not include_deleted:
        stmt = stmt.where(Project.deleted_at.is_(None))
    if current_user.role != "admin":
        stmt = stmt.where(Project.owner_id == current_user.id)
    return stmt
