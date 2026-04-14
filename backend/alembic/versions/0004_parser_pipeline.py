"""create document_texts / document_metadata / document_images / price_items + extend bid_documents/price_parsing_rules

Revision ID: 0004_parser_pipeline
Revises: 0003_files
Create Date: 2026-04-14

C5 parser-pipeline:
- 4 张新表(内容提取 3 张 + 报价项 1 张)
- bid_documents 新增 role_confidence 字段
- price_parsing_rules 新增 status 字段 + project 级 partial unique index
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB  # noqa: F401 (reserved for future)

# revision identifiers, used by Alembic.
revision = "0004_parser_pipeline"
down_revision = "0003_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------- document_texts
    op.create_table(
        "document_texts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "bid_document_id",
            sa.Integer(),
            sa.ForeignKey("bid_documents.id", name="fk_document_texts_doc_id"),
            nullable=False,
        ),
        sa.Column("paragraph_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("location", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_document_texts_doc_idx",
        "document_texts",
        ["bid_document_id", "paragraph_index"],
    )

    # ------------------------------------------------------- document_metadata
    op.create_table(
        "document_metadata",
        sa.Column(
            "bid_document_id",
            sa.Integer(),
            sa.ForeignKey(
                "bid_documents.id", name="fk_document_metadata_doc_id"
            ),
            primary_key=True,
        ),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("last_saved_by", sa.String(length=200), nullable=True),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column(
            "doc_created_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "doc_modified_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("app_name", sa.String(length=100), nullable=True),
        sa.Column("app_version", sa.String(length=50), nullable=True),
    )

    # ---------------------------------------------------------- document_images
    op.create_table(
        "document_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "bid_document_id",
            sa.Integer(),
            sa.ForeignKey(
                "bid_documents.id", name="fk_document_images_doc_id"
            ),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("md5", sa.String(length=32), nullable=False),
        sa.Column("phash", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("position", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_document_images_doc_md5",
        "document_images",
        ["bid_document_id", "md5"],
    )

    # ---------------------------------------------------------- price_items
    op.create_table(
        "price_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "bidder_id",
            sa.Integer(),
            sa.ForeignKey("bidders.id", name="fk_price_items_bidder_id"),
            nullable=False,
        ),
        sa.Column(
            "price_parsing_rule_id",
            sa.Integer(),
            sa.ForeignKey(
                "price_parsing_rules.id",
                name="fk_price_items_rule_id",
            ),
            nullable=False,
        ),
        sa.Column("sheet_name", sa.String(length=200), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("item_code", sa.String(length=200), nullable=True),
        sa.Column("item_name", sa.String(length=500), nullable=True),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column(
            "unit_price", sa.Numeric(precision=18, scale=2), nullable=True
        ),
        sa.Column(
            "total_price", sa.Numeric(precision=18, scale=2), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_price_items_bidder_rule",
        "price_items",
        ["bidder_id", "price_parsing_rule_id"],
    )

    # ---------------------------------------- bid_documents.role_confidence
    op.add_column(
        "bid_documents",
        sa.Column("role_confidence", sa.String(length=16), nullable=True),
    )

    # ---------------------------------------- price_parsing_rules.status + unique
    op.add_column(
        "price_parsing_rules",
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="identifying",
        ),
    )
    # 项目级"仅一条识别中或已确认规则";SQLite 单测下跳过 partial unique
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            "uq_price_rules_project_active",
            "price_parsing_rules",
            ["project_id"],
            unique=True,
            postgresql_where=sa.text(
                "status IN ('identifying','confirmed')"
            ),
        )
    else:
        # SQLite:建普通索引,并发唯一性由应用层保证(单测场景)
        op.create_index(
            "uq_price_rules_project_active",
            "price_parsing_rules",
            ["project_id"],
        )


def downgrade() -> None:
    op.drop_index(
        "uq_price_rules_project_active", table_name="price_parsing_rules"
    )
    op.drop_column("price_parsing_rules", "status")
    op.drop_column("bid_documents", "role_confidence")
    op.drop_index("ix_price_items_bidder_rule", table_name="price_items")
    op.drop_table("price_items")
    op.drop_index("ix_document_images_doc_md5", table_name="document_images")
    op.drop_table("document_images")
    op.drop_table("document_metadata")
    op.drop_index("ix_document_texts_doc_idx", table_name="document_texts")
    op.drop_table("document_texts")
