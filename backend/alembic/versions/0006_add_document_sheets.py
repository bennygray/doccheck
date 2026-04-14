"""create document_sheets

Revision ID: 0006_add_document_sheets
Revises: 0005_detect_framework
Create Date: 2026-04-15

C9 detect-agent-structure-similarity:
- document_sheets: xlsx cell 级数据(rows + merged_cells)供 C9 结构维度消费
- 与 document_texts(sheet 合并文本)并行,不冲突
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_add_document_sheets"
down_revision = "0005_detect_framework"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    json_type = sa.JSON().with_variant(
        sa.dialects.postgresql.JSONB(), "postgresql"
    )

    op.create_table(
        "document_sheets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "bid_document_id",
            sa.Integer(),
            sa.ForeignKey(
                "bid_documents.id", name="fk_document_sheets_doc_id"
            ),
            nullable=False,
        ),
        sa.Column("sheet_index", sa.Integer(), nullable=False),
        sa.Column("sheet_name", sa.String(length=255), nullable=False),
        sa.Column(
            "hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false") if is_pg else sa.text("0"),
        ),
        sa.Column("rows_json", json_type, nullable=False),
        sa.Column(
            "merged_cells_json",
            json_type,
            nullable=False,
            server_default=sa.text("'[]'") if is_pg else sa.text("'[]'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "bid_document_id",
            "sheet_index",
            name="uq_document_sheets_doc_idx",
        ),
    )
    op.create_index(
        "ix_document_sheets_doc",
        "document_sheets",
        ["bid_document_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_sheets_doc", table_name="document_sheets")
    op.drop_table("document_sheets")
