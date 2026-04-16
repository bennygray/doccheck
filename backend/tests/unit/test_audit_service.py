"""L1 - audit.log_action (C15 report-export, spec audit-log §写入失败不影响主业务)

验证:
- 合法 action 正常写入,before/after JSON round-trip
- 非法 action 抛 ValueError,不写入
- DB 异常时吞异常(不抛),logger 有 error
- 从 FastAPI Request 抽取 ip / user-agent(含 X-Forwarded-For)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from starlette.datastructures import Headers
from starlette.requests import Request

from app.db.session import async_session
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.user import User
from app.services import audit as audit_service


@pytest_asyncio.fixture
async def seed():
    async with async_session() as session:
        for M in (AuditLog, Project, User):
            await session.execute(delete(M))
        user = User(
            username="audsvc",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        session.add(user)
        await session.flush()
        project = Project(name="P-audsvc", owner_id=user.id)
        session.add(project)
        await session.flush()
        await session.commit()
        yield {"user_id": user.id, "project_id": project.id}
    async with async_session() as session:
        for M in (AuditLog, Project, User):
            await session.execute(delete(M))
        await session.commit()


def _build_request(
    *, client_host: str = "1.2.3.4", headers: dict[str, str] | None = None
) -> Request:
    raw_headers = []
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode(), v.encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/test",
        "headers": raw_headers,
        "client": (client_host, 12345),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_log_action_happy_path(seed):
    req = _build_request(
        headers={"user-agent": "pytest/1.0", "x-forwarded-for": "9.9.9.9, 10.0.0.1"}
    )
    await audit_service.log_action(
        action="review.report_confirmed",
        project_id=seed["project_id"],
        actor_id=seed["user_id"],
        target_type="report",
        target_id="1",
        before={"status": None, "comment": None},
        after={"status": "confirmed", "comment": "ok"},
        request=req,
    )
    async with async_session() as session:
        row = (await session.execute(select(AuditLog))).scalar_one()
    assert row.action == "review.report_confirmed"
    assert row.before_json == {"status": None, "comment": None}
    assert row.after_json == {"status": "confirmed", "comment": "ok"}
    # X-Forwarded-For 取第一个
    assert row.ip == "9.9.9.9"
    assert row.user_agent == "pytest/1.0"


@pytest.mark.asyncio
async def test_log_action_no_request_no_meta(seed):
    await audit_service.log_action(
        action="export.requested",
        project_id=seed["project_id"],
        actor_id=seed["user_id"],
        target_type="export",
        target_id="99",
    )
    async with async_session() as session:
        row = (await session.execute(select(AuditLog))).scalar_one()
    assert row.action == "export.requested"
    assert row.ip is None
    assert row.user_agent is None
    assert row.before_json is None
    assert row.after_json is None


@pytest.mark.asyncio
async def test_log_action_illegal_action_raises(seed):
    with pytest.raises(ValueError, match="invalid audit action"):
        await audit_service.log_action(
            action="foo.bar",
            project_id=seed["project_id"],
            actor_id=seed["user_id"],
            target_type="report",
        )
    # 未写入
    async with async_session() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_log_action_db_failure_swallowed(seed, caplog):
    """模拟 session.commit 抛异常 — 函数不得抛,但要 log error。"""
    import logging

    class _Boom(Exception):
        pass

    # patch async_session() 返回的上下文,让 commit 抛错
    class _FakeSession:
        def __init__(self):
            self.add = lambda *_: None

        async def commit(self):
            raise _Boom("simulated db error")

    class _FakeCM:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *args):
            return False

    with patch.object(audit_service, "async_session", lambda: _FakeCM()):
        with caplog.at_level(logging.ERROR, logger="app.services.audit"):
            # 不应抛
            await audit_service.log_action(
                action="review.report_rejected",
                project_id=seed["project_id"],
                actor_id=seed["user_id"],
                target_type="report",
            )
    # 确认有 error 日志
    assert any("audit.log_action failed" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_log_action_all_review_actions(seed):
    """覆盖 5 个 review 类 action 均能写入。"""
    for action in (
        "review.report_confirmed",
        "review.report_rejected",
        "review.report_downgraded",
        "review.report_upgraded",
        "review.dimension_marked",
    ):
        await audit_service.log_action(
            action=action,
            project_id=seed["project_id"],
            actor_id=seed["user_id"],
            target_type="report",
        )
    async with async_session() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
    actions = {r.action for r in rows}
    assert actions == {
        "review.report_confirmed",
        "review.report_rejected",
        "review.report_downgraded",
        "review.report_upgraded",
        "review.dimension_marked",
    }
