"""create users table and seed default admin

Revision ID: 0001_users
Revises:
Create Date: 2026-04-14

C2 auth:
- 新建 users 表(含 login_fail_count / locked_until / must_change_password / password_changed_at)
- seed 默认管理员(username/password 可由 env AUTH_SEED_ADMIN_USERNAME/PASSWORD 覆盖)
- INSERT ... ON CONFLICT (username) DO NOTHING 保证多次执行幂等
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# passlib 在迁移里动态算哈希(避免固定哈希污染迁移文件)
from passlib.context import CryptContext

from app.core.config import settings

# revision identifiers, used by Alembic.
revision = "0001_users"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            server_default="reviewer",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "login_fail_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "locked_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
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
    op.create_unique_constraint("uq_users_username", "users", ["username"])
    op.create_index("ix_users_username", "users", ["username"])

    # seed 默认 admin(幂等)
    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    admin_hash = pwd_ctx.hash(settings.auth_seed_admin_password)

    # 使用 raw SQL + ON CONFLICT,alembic 的 bulk_insert 不支持 ON CONFLICT
    op.execute(
        sa.text(
            """
            INSERT INTO users
                (username, password_hash, role, is_active, must_change_password)
            VALUES
                (:username, :password_hash, 'admin', TRUE, TRUE)
            ON CONFLICT (username) DO NOTHING
            """
        ).bindparams(
            username=settings.auth_seed_admin_username,
            password_hash=admin_hash,
        )
    )


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_constraint("uq_users_username", "users", type_="unique")
    op.drop_table("users")
