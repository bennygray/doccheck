"""analysis_reports: add template_cluster_detected + template_cluster_adjusted_scores

Revision ID: 0012_template_cluster
Revises: 0011_prr_sheets_config
Create Date: 2026-04-25

CH-2 detect-template-exclusion:
- template_cluster_detected BOOLEAN NOT NULL DEFAULT FALSE(历史行回填 false)
- template_cluster_adjusted_scores JSONB NULL(仅本 change 后命中模板簇的 report 有值)

prod 一旦消费新字段建议前进修复而非 rollback;downgrade 会丢失模板簇审计数据。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "0012_template_cluster"
down_revision = "0011_prr_sheets_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_reports",
        sa.Column(
            "template_cluster_detected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "analysis_reports",
        sa.Column(
            "template_cluster_adjusted_scores",
            JSONB,
            nullable=True,
        ),
    )
    # 历史行回填后,清除 server_default 让应用层负责后续插入(常规模式)
    op.alter_column(
        "analysis_reports",
        "template_cluster_detected",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("analysis_reports", "template_cluster_adjusted_scores")
    op.drop_column("analysis_reports", "template_cluster_detected")
