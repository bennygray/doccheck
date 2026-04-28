"""price_parsing_rules: backfill sheet_role='main' to existing sheets_config items

Revision ID: 0013_sheet_role
Revises: 0012_template_cluster
Create Date: 2026-04-28

fix-multi-sheet-price-double-count B:
- sheets_config[*] 加 sheet_role 字段(枚举: main/breakdown/summary)
- 老数据回填默认 'main'(行为同改前)
- 不改 schema 列;只改 JSONB 内容 — 应用层 SQL COALESCE 仍兜底缺字段
"""

from __future__ import annotations

from alembic import op


revision = "0013_sheet_role"
down_revision = "0012_template_cluster"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """对所有 price_parsing_rules.sheets_config 数组项补 sheet_role='main'(若缺)。

    使用 PostgreSQL JSONB 操作:对每项,若 'sheet_role' 字段不存在则 || 上对象。
    """
    op.execute("""
        UPDATE price_parsing_rules
        SET sheets_config = (
            SELECT jsonb_agg(
                CASE
                    WHEN elem ? 'sheet_role' THEN elem
                    ELSE elem || jsonb_build_object('sheet_role', 'main')
                END
            )
            FROM jsonb_array_elements(sheets_config) AS elem
        )
        WHERE jsonb_typeof(sheets_config) = 'array'
          AND jsonb_array_length(sheets_config) > 0
    """)


def downgrade() -> None:
    """从 sheets_config 每项移除 sheet_role 字段(若存在)。"""
    op.execute("""
        UPDATE price_parsing_rules
        SET sheets_config = (
            SELECT jsonb_agg(elem - 'sheet_role')
            FROM jsonb_array_elements(sheets_config) AS elem
        )
        WHERE jsonb_typeof(sheets_config) = 'array'
          AND jsonb_array_length(sheets_config) > 0
    """)
