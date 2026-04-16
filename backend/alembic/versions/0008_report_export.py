"""create audit_logs / export_jobs / export_templates + AR/OA review fields

Revision ID: 0008_report_export
Revises: 0007_add_doc_meta_template
Create Date: 2026-04-16

C15 report-export:
- 新建 audit_logs(独立审计日志表,B2 独立)
- 新建 export_jobs(独立导出作业表,B2 决策)
- 新建 export_templates(用户模板骨架预留)
- AR 加 4 人工复核字段(整报告级)
- OA 加 manual_review_json(维度级)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision = "0008_report_export"
down_revision = "0007_add_doc_meta_template"
branch_labels = None
depends_on = None


def _jsonb_type(is_pg: bool) -> sa.types.TypeEngine:
    # JSONB on PG, JSON fallback on SQLite
    return JSONB() if is_pg else sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    json_type = _jsonb_type(is_pg)

    # ---------------------------------------------------------- export_templates
    op.create_table(
        "export_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_export_templates_owner_id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ---------------------------------------------------------- audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", name="fk_audit_logs_project_id"),
            nullable=False,
        ),
        sa.Column(
            "report_id",
            sa.Integer(),
            sa.ForeignKey(
                "analysis_reports.id", name="fk_audit_logs_report_id"
            ),
            nullable=True,
        ),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_audit_logs_actor_id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("before_json", json_type, nullable=True),
        sa.Column("after_json", json_type, nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_audit_logs_project_created",
        "audit_logs",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_audit_logs_report_created",
        "audit_logs",
        ["report_id", "created_at"],
    )

    # ---------------------------------------------------------- export_jobs
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", name="fk_export_jobs_project_id"),
            nullable=False,
        ),
        sa.Column(
            "report_id",
            sa.Integer(),
            sa.ForeignKey(
                "analysis_reports.id", name="fk_export_jobs_report_id"
            ),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_export_jobs_actor_id"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey(
                "export_templates.id", name="fk_export_jobs_template_id"
            ),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("file_path", sa.String(length=512), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column(
            "fallback_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "file_expired",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_export_jobs_project_created",
        "export_jobs",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_export_jobs_report_created",
        "export_jobs",
        ["report_id", "created_at"],
    )
    op.create_index(
        "ix_export_jobs_status_finished",
        "export_jobs",
        ["status", "finished_at"],
    )

    # ---------------------------------------------------------- AR 扩字段
    op.add_column(
        "analysis_reports",
        sa.Column(
            "manual_review_status", sa.String(length=16), nullable=True
        ),
    )
    op.add_column(
        "analysis_reports",
        sa.Column("manual_review_comment", sa.Text(), nullable=True),
    )
    op.add_column(
        "analysis_reports",
        sa.Column(
            "reviewer_id",
            sa.Integer(),
            sa.ForeignKey(
                "users.id", name="fk_analysis_reports_reviewer_id"
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "analysis_reports",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ---------------------------------------------------------- OA 扩字段
    op.add_column(
        "overall_analyses",
        sa.Column("manual_review_json", json_type, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("overall_analyses", "manual_review_json")

    op.drop_column("analysis_reports", "reviewed_at")
    op.drop_column("analysis_reports", "reviewer_id")
    op.drop_column("analysis_reports", "manual_review_comment")
    op.drop_column("analysis_reports", "manual_review_status")

    op.drop_index("ix_export_jobs_status_finished", table_name="export_jobs")
    op.drop_index("ix_export_jobs_report_created", table_name="export_jobs")
    op.drop_index("ix_export_jobs_project_created", table_name="export_jobs")
    op.drop_table("export_jobs")

    op.drop_index("ix_audit_logs_report_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_project_created", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_table("export_templates")
