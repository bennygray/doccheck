"""tender_documents: 招标方下发的招标文件 (detect-tender-baseline D1)

Revision ID: 0014_tender_document
Revises: 0013_sheet_role
Create Date: 2026-04-30

详见 openspec/changes/detect-tender-baseline/design.md D1。

零数据迁移、向前兼容(老数据保留只读,新表为空)。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0014_tender_document"
down_revision = "0013_sheet_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tender_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("md5", sa.String(32), nullable=False),
        sa.Column(
            "parse_status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("parse_error", sa.String(500), nullable=True),
        # apply 简化:tender 段 hash 集合直接存 JSONB,不入 DocumentText 表
        sa.Column(
            "segment_hashes",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "boq_baseline_hashes",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "project_id", "md5", name="uq_tender_documents_project_md5"
        ),
    )
    op.create_index(
        "ix_tender_documents_project_status",
        "tender_documents",
        ["project_id", "parse_status", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tender_documents_project_status", table_name="tender_documents"
    )
    op.drop_table("tender_documents")
