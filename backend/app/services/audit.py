"""audit.log_action — 独立事务 + try/except 吞异常的审计日志入口 (C15 report-export)

设计约束 (design D12 + spec audit-log):
- 独立 session,不与主业务事务共享(主业务回滚不影响已写 audit)
- 非法 action 抛 ValueError(白名单在 app.models.audit_log.AUDIT_ACTIONS)
- DB 错误吞掉 + logger.error,主业务不受影响
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from fastapi import Request

from app.db.session import async_session
from app.models.audit_log import AUDIT_ACTIONS, AuditLog

logger = logging.getLogger(__name__)


def _extract_request_meta(
    request: Request | None,
) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    ip = None
    # 兼容反向代理 X-Forwarded-For,取第一个非空
    xff = request.headers.get("x-forwarded-for")
    if xff:
        ip = xff.split(",")[0].strip() or None
    if not ip and request.client is not None:
        ip = request.client.host
    ua = request.headers.get("user-agent")
    if ua is not None:
        ua = ua[:255]
    return ip, ua


async def log_action(
    *,
    action: str,
    project_id: int,
    actor_id: int,
    target_type: str,
    report_id: int | None = None,
    target_id: str | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """写一条审计日志。

    非法 action 抛 ValueError(不落库);DB 错误吞掉仅 log,不抛出。
    """
    if action not in AUDIT_ACTIONS:
        raise ValueError(f"invalid audit action: {action!r}")

    ip, ua = _extract_request_meta(request)
    row = AuditLog(
        project_id=project_id,
        report_id=report_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_json=dict(before) if before is not None else None,
        after_json=dict(after) if after is not None else None,
        ip=ip,
        user_agent=ua,
    )

    try:
        async with async_session() as session:
            session.add(row)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - 审计失败不阻塞主业务
        logger.error(
            "audit.log_action failed: action=%s project=%s actor=%s err=%s",
            action,
            project_id,
            actor_id,
            exc,
        )


__all__ = ["log_action"]
