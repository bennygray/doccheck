"""L1 - parser/pipeline/progress_broker 单元测试 (C5 §9.9)"""

from __future__ import annotations

import asyncio

import pytest

from app.services.parser.pipeline.progress_broker import ProgressBroker


@pytest.mark.asyncio
async def test_subscribe_publish_delivered() -> None:
    broker = ProgressBroker()
    q = broker.subscribe(1)
    await broker.publish(1, "bidder_status_changed", {"bidder_id": 42, "new_status": "identified"})
    event = await asyncio.wait_for(q.get(), timeout=1)
    assert event.event_type == "bidder_status_changed"
    assert event.data == {"bidder_id": 42, "new_status": "identified"}


@pytest.mark.asyncio
async def test_multi_subscribers_all_receive() -> None:
    broker = ProgressBroker()
    q1 = broker.subscribe(1)
    q2 = broker.subscribe(1)
    await broker.publish(1, "heartbeat", {"ts": "now"})
    e1 = await asyncio.wait_for(q1.get(), timeout=1)
    e2 = await asyncio.wait_for(q2.get(), timeout=1)
    assert e1.data == e2.data == {"ts": "now"}


@pytest.mark.asyncio
async def test_no_subscribers_publish_noop() -> None:
    broker = ProgressBroker()
    # 无订阅者 publish 不抛
    await broker.publish(99, "error", {"msg": "x"})


@pytest.mark.asyncio
async def test_unsubscribe_removes_queue() -> None:
    broker = ProgressBroker()
    q = broker.subscribe(1)
    assert broker.subscriber_count(1) == 1
    broker.unsubscribe(1, q)
    assert broker.subscriber_count(1) == 0


@pytest.mark.asyncio
async def test_unsubscribe_unknown_queue_is_noop() -> None:
    broker = ProgressBroker()
    q_alien = asyncio.Queue()
    # 从未订阅过的 queue 也不抛
    broker.unsubscribe(1, q_alien)


@pytest.mark.asyncio
async def test_cross_project_isolation() -> None:
    broker = ProgressBroker()
    q_p1 = broker.subscribe(1)
    q_p2 = broker.subscribe(2)
    await broker.publish(1, "heartbeat", {"n": "1"})
    # p1 收到,p2 不应收
    e = await asyncio.wait_for(q_p1.get(), timeout=1)
    assert e.data == {"n": "1"}
    assert q_p2.empty()
