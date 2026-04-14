"""登录失败计数与锁定状态机 (C2 auth, design.md D4)

状态机:
- fail → login_fail_count += 1
  若达阈值 → locked_until = now + TTL,同时清零计数(下次再错从 0 起算,避免永久锁)
- 登录前 check_locked:locked_until > now → 返回剩余时长;否则 None
- 登录成功 → 清零 login_fail_count,locked_until = None

并发处理:调用方负责用 `with_for_update()` 锁行;本模块只做纯状态变更。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models.user import User


def check_locked(user: User) -> timedelta | None:
    """返回剩余锁定时间,未锁返回 None。"""
    if user.locked_until is None:
        return None
    now = datetime.now(timezone.utc)
    # locked_until 从 DB 取出带 tz (DateTime(timezone=True))
    if user.locked_until <= now:
        return None
    return user.locked_until - now


def record_failure(user: User) -> bool:
    """记录一次失败。达阈值时设 locked_until 并清零计数。

    返回 True 表示**本次触发**了新的锁定(用于日志/告警);否则 False。
    调用方须在事务中持行锁(with_for_update)后调用,再 commit。
    """
    user.login_fail_count = (user.login_fail_count or 0) + 1
    if user.login_fail_count >= settings.auth_lockout_threshold:
        user.locked_until = datetime.now(timezone.utc) + timedelta(
            minutes=settings.auth_lockout_ttl_minutes
        )
        user.login_fail_count = 0  # 清零,避免"永久锁"
        return True
    return False


def reset_failure(user: User) -> None:
    """登录成功后清零失败状态。"""
    user.login_fail_count = 0
    user.locked_until = None
