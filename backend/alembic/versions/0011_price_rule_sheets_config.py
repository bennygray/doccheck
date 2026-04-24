"""price_parsing_rules: column_mapping -> sheets_config multi-sheet

Revision ID: 0011_prr_sheets_config
Revises: 0010_llm_default
Create Date: 2026-04-25

parser-accuracy-fixes P1-5 + H2:
- 加 sheets_config JSONB 列(权威)
- 转老数据:[{sheet_name, header_row, column_mapping}] 包一层(失败态 rule 保持空数组)
- 老列 sheet_name/header_row/column_mapping 改 NULLABLE(新 rule 可只写 sheets_config)
- 老列保留不 drop,做 backward compat 缓冲(老 admin UI GET 仍可读)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "0011_prr_sheets_config"
down_revision = "0010_llm_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: 加 sheets_config 列 JSONB NOT NULL,临时 DEFAULT '[]'
    op.add_column(
        "price_parsing_rules",
        sa.Column(
            "sheets_config",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # Step 2: 老数据自动转换
    # - 只处理 column_mapping 非空且非 '{}' 的 rule(排除失败态)
    # - 失败态(status='failed' or column_mapping NULL/{})保留 sheets_config=[]
    op.execute(
        """
        UPDATE price_parsing_rules
        SET sheets_config = jsonb_build_array(
            jsonb_build_object(
                'sheet_name', sheet_name,
                'header_row', header_row,
                'column_mapping', column_mapping
            )
        )
        WHERE sheets_config = '[]'::jsonb
          AND column_mapping IS NOT NULL
          AND column_mapping::text != '{}';
        """
    )

    # Step 3: DROP DEFAULT 防止后续 INSERT 不带 sheets_config 造成数据遗漏
    op.execute(
        "ALTER TABLE price_parsing_rules ALTER COLUMN sheets_config DROP DEFAULT;"
    )

    # Step 4 (H2): 老 3 列改 NULLABLE,新写入路径可以不传(sheets_config 是新权威)
    op.alter_column(
        "price_parsing_rules", "sheet_name", existing_type=sa.String(200), nullable=True
    )
    op.alter_column(
        "price_parsing_rules", "header_row", existing_type=sa.Integer(), nullable=True
    )
    op.alter_column(
        "price_parsing_rules",
        "column_mapping",
        existing_type=JSONB,
        nullable=True,
    )


def downgrade() -> None:
    # 降级前兜底回写 sheets_config[0] 到老列(数据不丢)
    # 仅处理 sheets_config 非空 且 老列至少一个 NULL 的行(防覆盖已有老数据)
    op.execute(
        """
        UPDATE price_parsing_rules
        SET sheet_name = (sheets_config -> 0 ->> 'sheet_name'),
            header_row = (sheets_config -> 0 ->> 'header_row')::int,
            column_mapping = (sheets_config -> 0 -> 'column_mapping')
        WHERE jsonb_array_length(sheets_config) >= 1
          AND (sheet_name IS NULL OR header_row IS NULL OR column_mapping IS NULL);
        """
    )

    # 老 3 列恢复 NOT NULL
    op.alter_column(
        "price_parsing_rules", "sheet_name", existing_type=sa.String(200), nullable=False
    )
    op.alter_column(
        "price_parsing_rules", "header_row", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "price_parsing_rules",
        "column_mapping",
        existing_type=JSONB,
        nullable=False,
    )

    # Drop sheets_config 列
    op.drop_column("price_parsing_rules", "sheets_config")
