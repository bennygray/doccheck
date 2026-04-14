"""create bidders / bid_documents / price_config / price_parsing_rules

Revision ID: 0003_files
Revises: 0002_projects
Create Date: 2026-04-14

C4 file-upload:
- 4 张新表(投标人 / 投标文件 / 项目报价元配置 / 报价列映射规则)
- bidders: 项目级权限挂靠 + 软删 + 同项目活跃 name 唯一(partial unique index)
- bid_documents: 投标人级 MD5 去重 (UNIQUE(bidder_id, md5));硬删,依附 bidder
- project_price_configs: 1:1 与 projects(project_id 同时是 PK + FK)
- price_parsing_rules: 1 项目对多 sheet 规则;column_mapping JSONB
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "0003_files"
down_revision = "0002_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------- bidders
    op.create_table(
        "bidders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", name="fk_bidders_project_id"),
            nullable=False,
        ),
        sa.Column(
            "parse_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("parse_error", sa.String(length=500), nullable=True),
        sa.Column(
            "file_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        # JSONB on PG;SQLAlchemy generic JSON 在 PG 下默认转 JSON,
        # 此处强制 JSONB 以便后续支持 GIN 索引(C5+)
        sa.Column(
            "identity_info",
            JSONB(),
            nullable=True,
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
    op.create_index(
        "ix_bidders_project_deleted",
        "bidders",
        ["project_id", "deleted_at"],
    )
    # 同项目活跃投标人 name 唯一(partial unique index;PG 中 NULL 视为 distinct,
    # 普通 UniqueConstraint 无法防 (pid, name, NULL) 重复)
    op.create_index(
        "uq_bidders_project_name_alive",
        "bidders",
        ["project_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ----------------------------------------------------------- bid_documents
    op.create_table(
        "bid_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "bidder_id",
            sa.Integer(),
            sa.ForeignKey("bidders.id", name="fk_bid_documents_bidder_id"),
            nullable=False,
        ),
        sa.Column("file_name", sa.String(length=500), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("file_type", sa.String(length=32), nullable=False),
        sa.Column("md5", sa.String(length=32), nullable=False),
        sa.Column("file_role", sa.String(length=32), nullable=True),
        sa.Column(
            "parse_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("parse_error", sa.String(length=500), nullable=True),
        sa.Column("source_archive", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "bidder_id", "md5", name="uq_bid_documents_bidder_md5"
        ),
    )
    op.create_index("ix_bid_documents_bidder_id", "bid_documents", ["bidder_id"])

    # ----------------------------------------------------- project_price_configs
    op.create_table(
        "project_price_configs",
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", name="fk_price_configs_project_id"),
            primary_key=True,
        ),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("tax_inclusive", sa.Boolean(), nullable=False),
        sa.Column("unit_scale", sa.String(length=16), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ----------------------------------------------------- price_parsing_rules
    op.create_table(
        "price_parsing_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", name="fk_price_rules_project_id"),
            nullable=False,
        ),
        sa.Column("sheet_name", sa.String(length=200), nullable=False),
        sa.Column("header_row", sa.Integer(), nullable=False),
        sa.Column(
            "column_mapping",
            JSONB(),
            nullable=False,
        ),
        sa.Column(
            "created_by_llm",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
    )
    op.create_index(
        "ix_price_rules_project_sheet",
        "price_parsing_rules",
        ["project_id", "sheet_name"],
    )


def downgrade() -> None:
    # 按 FK 依赖反向 DROP:子表先 → 父表后
    op.drop_index("ix_price_rules_project_sheet", table_name="price_parsing_rules")
    op.drop_table("price_parsing_rules")
    op.drop_table("project_price_configs")
    op.drop_index("ix_bid_documents_bidder_id", table_name="bid_documents")
    op.drop_table("bid_documents")
    op.drop_index("uq_bidders_project_name_alive", table_name="bidders")
    op.drop_index("ix_bidders_project_deleted", table_name="bidders")
    op.drop_table("bidders")
