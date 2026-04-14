"""add document_metadata.template

Revision ID: 0007_add_document_metadata_template
Revises: 0006_add_document_sheets
Create Date: 2026-04-15

C10 detect-agents-metadata:
- document_metadata 表新增 template VARCHAR(255) NULL 列
- 供 metadata_machine Agent 的三字段元组(app_name + app_version + template)碰撞
- 历史数据需运维跑 backend/scripts/backfill_document_metadata_template.py 回填
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# (revision 字符串受 alembic_version.version_num VARCHAR(32) 限制,需 ≤ 32 chars)
revision = "0007_add_doc_meta_template"
down_revision = "0006_add_document_sheets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_metadata",
        sa.Column("template", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_metadata", "template")
