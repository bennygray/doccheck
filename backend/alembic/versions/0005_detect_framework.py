"""create agent_tasks / pair_comparisons / overall_analyses / analysis_reports / async_tasks

Revision ID: 0005_detect_framework
Revises: 0004_parser_pipeline
Create Date: 2026-04-14

C6 detect-framework:
- 5 张新表支撑 M3 异步检测框架
- agent_tasks 的 pair/global 一致性 CHECK 约束(PG 生效,SQLite 应用层保证)
- analysis_reports 的 project_id+version UNIQUE
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_detect_framework"
down_revision = "0004_parser_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # ---------------------------------------------------------- agent_tasks
    agent_tasks_args = [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", name="fk_agent_tasks_project_id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("agent_type", sa.String(length=16), nullable=False),
        sa.Column(
            "pair_bidder_a_id",
            sa.Integer(),
            sa.ForeignKey(
                "bidders.id", name="fk_agent_tasks_pair_a_id"
            ),
            nullable=True,
        ),
        sa.Column(
            "pair_bidder_b_id",
            sa.Integer(),
            sa.ForeignKey(
                "bidders.id", name="fk_agent_tasks_pair_b_id"
            ),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("summary", sa.String(length=500), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]
    if is_pg:
        agent_tasks_args.append(
            sa.CheckConstraint(
                "(agent_type = 'pair' "
                "AND pair_bidder_a_id IS NOT NULL "
                "AND pair_bidder_b_id IS NOT NULL) "
                "OR (agent_type = 'global' "
                "AND pair_bidder_a_id IS NULL "
                "AND pair_bidder_b_id IS NULL)",
                name="ck_agent_tasks_pair_bidder_consistency",
            )
        )
    op.create_table("agent_tasks", *agent_tasks_args)
    op.create_index(
        "ix_agent_tasks_project_version",
        "agent_tasks",
        ["project_id", "version"],
    )
    op.create_index(
        "ix_agent_tasks_status_started",
        "agent_tasks",
        ["status", "started_at"],
    )

    # ---------------------------------------------------------- pair_comparisons
    op.create_table(
        "pair_comparisons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey(
                "projects.id", name="fk_pair_comparisons_project_id"
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "bidder_a_id",
            sa.Integer(),
            sa.ForeignKey(
                "bidders.id", name="fk_pair_comparisons_bidder_a_id"
            ),
            nullable=False,
        ),
        sa.Column(
            "bidder_b_id",
            sa.Integer(),
            sa.ForeignKey(
                "bidders.id", name="fk_pair_comparisons_bidder_b_id"
            ),
            nullable=False,
        ),
        sa.Column("dimension", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column(
            "evidence_json",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "is_ironclad",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false") if is_pg else sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_pair_comparisons_project_version_dim",
        "pair_comparisons",
        ["project_id", "version", "dimension"],
    )

    # ---------------------------------------------------------- overall_analyses
    op.create_table(
        "overall_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey(
                "projects.id", name="fk_overall_analyses_project_id"
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("dimension", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column(
            "evidence_json",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_overall_analyses_project_version_dim",
        "overall_analyses",
        ["project_id", "version", "dimension"],
    )

    # ---------------------------------------------------------- analysis_reports
    op.create_table(
        "analysis_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey(
                "projects.id", name="fk_analysis_reports_project_id"
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "total_score", sa.Numeric(precision=6, scale=2), nullable=False
        ),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column(
            "llm_conclusion",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "project_id",
            "version",
            name="uq_analysis_reports_project_version",
        ),
    )

    # ---------------------------------------------------------- async_tasks
    op.create_table(
        "async_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subtype", sa.String(length=32), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_async_tasks_status_heartbeat",
        "async_tasks",
        ["status", "heartbeat_at"],
    )


def downgrade() -> None:
    # 按 FK 反序 DROP(都依赖 projects / bidders;async_tasks 无 FK 最灵活)
    op.drop_index(
        "ix_async_tasks_status_heartbeat", table_name="async_tasks"
    )
    op.drop_table("async_tasks")
    op.drop_table("analysis_reports")
    op.drop_index(
        "ix_overall_analyses_project_version_dim",
        table_name="overall_analyses",
    )
    op.drop_table("overall_analyses")
    op.drop_index(
        "ix_pair_comparisons_project_version_dim",
        table_name="pair_comparisons",
    )
    op.drop_table("pair_comparisons")
    op.drop_index(
        "ix_agent_tasks_status_started", table_name="agent_tasks"
    )
    op.drop_index(
        "ix_agent_tasks_project_version", table_name="agent_tasks"
    )
    op.drop_table("agent_tasks")
