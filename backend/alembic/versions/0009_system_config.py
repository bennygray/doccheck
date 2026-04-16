"""create system_configs table with default row

Revision ID: 0009_system_config
Revises: 0008_report_export
Create Date: 2026-04-16

C17 admin-users:
- 新建 system_configs（全局检测规则配置，单行存储）
- Insert 默认行 id=1
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.services.admin.rules_defaults import DEFAULT_RULES_CONFIG

# revision identifiers
revision = "0009_system_config"
down_revision = "0008_report_export"
branch_labels = None
depends_on = None


def _jsonb_type(is_pg: bool) -> sa.types.TypeEngine:
    return JSONB() if is_pg else sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    table = op.create_table(
        "system_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config", _jsonb_type(is_pg), nullable=False),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.bulk_insert(
        table,
        [{"id": 1, "config": json.loads(json.dumps(DEFAULT_RULES_CONFIG))}],
    )


def downgrade() -> None:
    op.drop_table("system_configs")
