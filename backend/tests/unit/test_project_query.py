"""L1: get_visible_projects_stmt 过滤逻辑 (C3 project-mgmt)。

锁定"软删过滤 + 角色过滤"两条规则不会在未来重构时被绕过,
对应 design.md D1 "软删泄露回归用例" 约束。

此测试使用 SQLite in-memory 创建表 + 插几条 Project,对 stmt 直接 execute。
这样单元测试可以在无 postgres 环境跑。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User


@pytest.fixture
def sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _mk_user(role: str, uid: int) -> User:
    # User ORM 对象,不入库,只作 helper 函数入参的容器
    u = User(
        username=f"u{uid}",
        password_hash="x" * 60,
        role=role,
        is_active=True,
    )
    u.id = uid
    return u


def _mk_project(
    session: Session,
    owner_id: int,
    name: str,
    deleted: bool = False,
) -> Project:
    now = datetime.now(timezone.utc)
    p = Project(
        name=name,
        owner_id=owner_id,
        status="draft",
        created_at=now,
        updated_at=now,
        deleted_at=now - timedelta(hours=1) if deleted else None,
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


class TestReviewerFiltering:
    def test_reviewer_sees_only_own(self, sqlite_session: Session) -> None:
        reviewer_a = _mk_user("reviewer", 1)
        _mk_project(sqlite_session, owner_id=1, name="A1")
        _mk_project(sqlite_session, owner_id=1, name="A2")
        _mk_project(sqlite_session, owner_id=2, name="B1")

        stmt = get_visible_projects_stmt(reviewer_a)
        rows = sqlite_session.execute(stmt).scalars().all()
        assert len(rows) == 2
        assert {r.name for r in rows} == {"A1", "A2"}

    def test_reviewer_excludes_soft_deleted(self, sqlite_session: Session) -> None:
        reviewer_a = _mk_user("reviewer", 1)
        _mk_project(sqlite_session, owner_id=1, name="A1")
        _mk_project(sqlite_session, owner_id=1, name="A-deleted", deleted=True)

        stmt = get_visible_projects_stmt(reviewer_a)
        rows = sqlite_session.execute(stmt).scalars().all()
        assert {r.name for r in rows} == {"A1"}


class TestAdminFiltering:
    def test_admin_sees_all_active(self, sqlite_session: Session) -> None:
        admin = _mk_user("admin", 99)
        _mk_project(sqlite_session, owner_id=1, name="A1")
        _mk_project(sqlite_session, owner_id=2, name="B1")
        _mk_project(sqlite_session, owner_id=3, name="C1")

        stmt = get_visible_projects_stmt(admin)
        rows = sqlite_session.execute(stmt).scalars().all()
        assert len(rows) == 3

    def test_admin_still_excludes_soft_deleted(
        self, sqlite_session: Session
    ) -> None:
        admin = _mk_user("admin", 99)
        _mk_project(sqlite_session, owner_id=1, name="A1")
        _mk_project(sqlite_session, owner_id=2, name="B-deleted", deleted=True)

        stmt = get_visible_projects_stmt(admin)
        rows = sqlite_session.execute(stmt).scalars().all()
        assert {r.name for r in rows} == {"A1"}


class TestIncludeDeletedFlag:
    def test_include_deleted_shows_everything_for_admin(
        self, sqlite_session: Session
    ) -> None:
        admin = _mk_user("admin", 99)
        _mk_project(sqlite_session, owner_id=1, name="A1")
        _mk_project(sqlite_session, owner_id=1, name="A-deleted", deleted=True)

        stmt = get_visible_projects_stmt(admin, include_deleted=True)
        rows = sqlite_session.execute(stmt).scalars().all()
        assert len(rows) == 2

    def test_include_deleted_respects_owner_filter_for_reviewer(
        self, sqlite_session: Session
    ) -> None:
        reviewer_a = _mk_user("reviewer", 1)
        _mk_project(sqlite_session, owner_id=1, name="A-deleted", deleted=True)
        _mk_project(sqlite_session, owner_id=2, name="B-deleted", deleted=True)

        stmt = get_visible_projects_stmt(reviewer_a, include_deleted=True)
        rows = sqlite_session.execute(stmt).scalars().all()
        assert {r.name for r in rows} == {"A-deleted"}


class TestRegressionGuard:
    """显式验证"忘加过滤"的回归风险被锁住。"""

    def test_no_role_means_reviewer_mode(self, sqlite_session: Session) -> None:
        """role 为 'reviewer' 以外任何值(比如未来新增 role)都保持 owner 过滤,
        而不是变成 admin 的全开放模式。"""
        weird_role = _mk_user("auditor", 1)  # 未定义角色
        _mk_project(sqlite_session, owner_id=1, name="own")
        _mk_project(sqlite_session, owner_id=2, name="other")

        stmt = get_visible_projects_stmt(weird_role)
        rows = sqlite_session.execute(stmt).scalars().all()
        # 非 admin 一律按 owner 过滤,保底
        assert {r.name for r in rows} == {"own"}

    def test_default_excludes_deleted(self, sqlite_session: Session) -> None:
        """不传 include_deleted 参数时,软删记录 MUST 被过滤。"""
        admin = _mk_user("admin", 99)
        _mk_project(sqlite_session, owner_id=1, name="alive")
        _mk_project(sqlite_session, owner_id=1, name="dead", deleted=True)

        stmt = get_visible_projects_stmt(admin)  # 不传 include_deleted
        rows = sqlite_session.execute(stmt).scalars().all()
        assert {r.name for r in rows} == {"alive"}
