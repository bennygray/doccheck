"""L1: 失败计数与锁定状态机 (C2).

纯内存测试,不依赖 DB — 直接操作 User ORM 实例的字段。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models.user import User
from app.services.auth.lockout import check_locked, record_failure, reset_failure


def _new_user() -> User:
    # 不入 DB,只用作字段容器
    u = User()
    u.login_fail_count = 0
    u.locked_until = None
    return u


def test_failures_below_threshold_do_not_lock():
    u = _new_user()
    for _ in range(settings.auth_lockout_threshold - 1):
        triggered = record_failure(u)
        assert triggered is False
    assert u.login_fail_count == settings.auth_lockout_threshold - 1
    assert u.locked_until is None


def test_threshold_failure_triggers_lockout_and_resets_count():
    u = _new_user()
    triggered = False
    for _ in range(settings.auth_lockout_threshold):
        triggered = record_failure(u)
    assert triggered is True
    assert u.locked_until is not None
    # 清零,避免"永久锁"
    assert u.login_fail_count == 0
    # 锁定时长接近配置值
    remaining = check_locked(u)
    assert remaining is not None
    assert remaining <= timedelta(minutes=settings.auth_lockout_ttl_minutes)
    assert remaining > timedelta(seconds=0)


def test_check_locked_returns_none_after_ttl():
    u = _new_user()
    # 人为设置 locked_until 到过去
    u.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert check_locked(u) is None


def test_reset_failure_clears_state():
    u = _new_user()
    u.login_fail_count = 3
    u.locked_until = datetime.now(timezone.utc) + timedelta(minutes=5)
    reset_failure(u)
    assert u.login_fail_count == 0
    assert u.locked_until is None


def test_check_locked_none_when_never_locked():
    u = _new_user()
    assert check_locked(u) is None
