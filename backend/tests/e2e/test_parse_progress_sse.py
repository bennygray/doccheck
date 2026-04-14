"""L2 - C5 SSE 解析进度事件流 (spec "解析进度 SSE 事件流")

注:用 ASGITransport 测完整 SSE 流时 aiter_lines 易阻塞(buffer 未满/连接未主动断);
故此文件分两层:
- 端点 404/订阅计数 → 走 HTTP 客户端(不消费流体内容)
- 事件推送/snapshot/heartbeat 逻辑 → 直接调 broker + _build_snapshot 辅助函数验证

这种分层保证覆盖 spec 所有 5 个 scenarios,同时避免 httpx stream 在测试环境下的
flaky 行为(与 CLAUDE.md 兜底原则一致:测试自己也要有可靠回路)。
"""

from __future__ import annotations

import asyncio
import os

import pytest_asyncio

from app.db.session import async_session
from app.services.parser.pipeline.progress_broker import (
    ProgressBroker,
    progress_broker,
)

from ._c4_helpers import seed_bidder, seed_project, seed_user

os.environ.setdefault("SSE_HEARTBEAT_INTERVAL_S", "0.2")
os.environ.setdefault("INFRA_DISABLE_PIPELINE", "1")


async def test_sse_cross_user_404(
    seeded_reviewer, reviewer_token, auth_client
):
    other = await seed_user("sseOther", role="reviewer")
    project = await seed_project(owner_id=other.id, name="OP")
    client = await auth_client(reviewer_token)
    r = await client.get(f"/api/projects/{project.id}/parse-progress")
    assert r.status_code == 404


# =============================================================================
# Broker 行为单测(本质上是集成逻辑,放 L2 因为覆盖 SSE spec)
# =============================================================================


async def test_broker_delivers_status_event(clean_users):
    # 独立 broker 实例,避免全局污染
    broker = ProgressBroker()
    q = broker.subscribe(999)
    await broker.publish(
        999, "bidder_status_changed", {"bidder_id": 1, "new_status": "identified"}
    )
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event.event_type == "bidder_status_changed"
    assert event.data == {"bidder_id": 1, "new_status": "identified"}


async def test_build_snapshot_format(
    seeded_reviewer, clean_users
):
    """首帧 snapshot 结构包含 bidders + progress 11 字段聚合。"""
    from app.api.routes.parse_progress import _build_snapshot

    project = await seed_project(owner_id=seeded_reviewer.id, name="SnapP")
    await seed_bidder(
        project_id=project.id, name="b1", parse_status="extracted"
    )
    await seed_bidder(
        project_id=project.id, name="b2", parse_status="identifying"
    )
    await seed_bidder(
        project_id=project.id, name="b3", parse_status="priced"
    )

    async with async_session() as s:
        snap = await _build_snapshot(s, project.id)

    assert len(snap["bidders"]) == 3
    prog = snap["progress"]
    assert prog["total_bidders"] == 3
    assert prog["extracted_count"] == 1
    assert prog["identifying_count"] == 1
    assert prog["priced_count"] == 1


async def test_broker_heartbeat_via_format_sse():
    """_format_sse 把事件格式化为 text/event-stream 协议帧。"""
    from app.api.routes.parse_progress import _format_sse

    out = _format_sse("heartbeat", {"ts": "2026-04-14T00:00:00Z"})
    assert "event: heartbeat" in out
    assert '"ts": "2026-04-14T00:00:00Z"' in out
    assert out.endswith("\n\n")


async def test_broker_unsubscribe_noop_on_unknown():
    broker = ProgressBroker()
    q = asyncio.Queue()
    # 未订阅就 unsubscribe → 不抛
    broker.unsubscribe(123, q)


async def test_global_broker_subscribe_count():
    """模块级 broker 应正常 subscribe/unsubscribe 计数。"""
    q = progress_broker.subscribe(77)
    try:
        assert progress_broker.subscriber_count(77) >= 1
    finally:
        progress_broker.unsubscribe(77, q)
    assert progress_broker.subscriber_count(77) == 0
