"""create projects table

Revision ID: 0002_projects
Revises: 0001_users
Create Date: 2026-04-14

C3 project-mgmt:
- 新建 projects 表(基础 CRUD + 软删 + 角色可见性)
- 联合索引 ``(owner_id, deleted_at, created_at)`` 支撑 reviewer 列表主路径
  (WHERE owner_id=? AND deleted_at IS NULL ORDER BY created_at DESC)
- 无 seed,C3 阶段由 API 创建第一条项目
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_projects"
down_revision = "0001_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("bid_code", sa.String(length=50), nullable=True),
        sa.Column("max_price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("risk_level", sa.String(length=16), nullable=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_projects_owner_id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # 单列 owner_id 索引(FK 查询优化)
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    # 联合索引覆盖 reviewer 列表主路径
    op.create_index(
        "ix_projects_owner_deleted_created",
        "projects",
        ["owner_id", "deleted_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_projects_owner_deleted_created", table_name="projects")
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_table("projects")
