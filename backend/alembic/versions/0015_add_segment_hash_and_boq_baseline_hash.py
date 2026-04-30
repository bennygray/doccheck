"""DocumentText.segment_hash + PriceItem.boq_baseline_hash (detect-tender-baseline D2/D5)

Revision ID: 0015_segment_and_boq_hash
Revises: 0014_tender_document
Create Date: 2026-04-30

新增:
- document_texts.segment_hash VARCHAR(64) NULL  归一化(NFKC + \\s+→' ' + strip)后 sha256
- price_items.boq_baseline_hash VARCHAR(64) NULL  (项目名+描述+单位+Decimal.normalize(工程量)) sha256

向后兼容:历史行 NULL,baseline_resolver lazy 跳过。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0015_segment_and_boq_hash"
down_revision = "0014_tender_document"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_texts",
        sa.Column("segment_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "price_items",
        sa.Column("boq_baseline_hash", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_items", "boq_baseline_hash")
    op.drop_column("document_texts", "segment_hash")
