"""L1 - pipeline 异常保护单元测试

覆盖:
- _safe_try_transition 捕获异常并记录日志
- _task_done callback 在 task 异常时记录 ERROR 日志
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.services.parser.pipeline.run_pipeline import _safe_try_transition
from app.services.parser.pipeline.trigger import _task_done


# --- 2.1: _safe_try_transition ---


@pytest.mark.asyncio
async def test_safe_try_transition_catches_exception(caplog: pytest.LogCaptureFixture) -> None:
    """try_transition_project_ready 抛异常时,_safe_try_transition 捕获并记录 ERROR。"""
    with patch(
        "app.services.parser.pipeline.run_pipeline.try_transition_project_ready",
        new_callable=AsyncMock,
        side_effect=RuntimeError("connection pool exhausted"),
    ):
        with caplog.at_level(logging.ERROR):
            await _safe_try_transition(project_id=42)

    assert any("try_transition_project_ready failed" in r.message for r in caplog.records)
    assert any("project=42" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_safe_try_transition_no_exception(caplog: pytest.LogCaptureFixture) -> None:
    """正常情况下不产生 ERROR 日志。"""
    with patch(
        "app.services.parser.pipeline.run_pipeline.try_transition_project_ready",
        new_callable=AsyncMock,
        return_value=True,
    ):
        with caplog.at_level(logging.ERROR):
            await _safe_try_transition(project_id=1)

    assert not any("try_transition_project_ready failed" in r.message for r in caplog.records)


# --- 2.2: _task_done callback ---


def test_task_done_logs_error_on_exception(caplog: pytest.LogCaptureFixture) -> None:
    """task 异常终止时 _task_done 记录 ERROR。"""
    loop = asyncio.new_event_loop()
    try:

        async def _failing():
            raise ValueError("boom")

        task = loop.create_task(_failing(), name="test-failing-task")
        loop.run_until_complete(asyncio.sleep(0.05))
    finally:
        loop.close()

    # task 现在已完成且携带异常
    with caplog.at_level(logging.ERROR):
        _task_done(task)

    assert any("pipeline task crashed" in r.message for r in caplog.records)


def test_task_done_no_log_on_success(caplog: pytest.LogCaptureFixture) -> None:
    """task 正常完成时 _task_done 不产生 ERROR。"""
    loop = asyncio.new_event_loop()
    try:

        async def _ok():
            return "done"

        task = loop.create_task(_ok(), name="test-ok-task")
        loop.run_until_complete(asyncio.sleep(0.05))
    finally:
        loop.close()

    with caplog.at_level(logging.ERROR):
        _task_done(task)

    assert not any("pipeline task crashed" in r.message for r in caplog.records)
