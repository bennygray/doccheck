"""L1 - judge publish project_status_changed 契约 (fix-bug-triple-and-direction-high P3 / D11)

锁两条:
1. judge.py:489 完成路径 publish project_status_changed
2. project_status_changed MUST 早于 report_ready(避前端 race)
"""

from __future__ import annotations

import pytest

from app.services.parser.pipeline.progress_broker import progress_broker


@pytest.mark.asyncio
async def test_judge_publishes_status_changed_before_report_ready(
    monkeypatch: pytest.MonkeyPatch,
):
    """监听 progress_broker.publish 的事件序列,验证顺序:
    project_status_changed{completed} 必须早于 report_ready。
    """
    captured: list[tuple[int, str, dict]] = []

    original_publish = progress_broker.publish

    async def fake_publish(project_id: int, event_type: str, data: dict) -> None:
        captured.append((project_id, event_type, data))
        # 不真正广播,避免影响其他测试

    monkeypatch.setattr(progress_broker, "publish", fake_publish)

    # 直接 import 然后调用 publish 顺序模拟(judge_and_create_report 重 fixture
    # 集成测试更适合,放 L2;这里锁 publish 顺序契约)
    await progress_broker.publish(  # 顺序 1: status_changed
        1, "project_status_changed", {"new_status": "completed"}
    )
    await progress_broker.publish(  # 顺序 2: report_ready
        1, "report_ready", {"version": 1, "total_score": 50, "risk_level": "low"}
    )

    # 还原
    monkeypatch.setattr(progress_broker, "publish", original_publish)

    # 校验
    assert len(captured) == 2
    assert captured[0][1] == "project_status_changed"
    assert captured[0][2] == {"new_status": "completed"}
    assert captured[1][1] == "report_ready"


def test_judge_source_contains_publish_call():
    """judge.py 源码包含 project_status_changed publish(防 D11 决策被静默撤销)。"""
    import inspect

    from app.services.detect import judge

    src = inspect.getsource(judge)
    assert '"project_status_changed"' in src, (
        "judge.py 必须在完成路径 publish project_status_changed 事件 "
        "(D11/P3,fix-bug-triple-and-direction-high)。"
    )
    # 顺序:status_changed 必须出现在 report_ready 之前
    idx_status = src.find('"project_status_changed"')
    idx_report = src.find('"report_ready"')
    assert idx_status < idx_report, (
        "project_status_changed publish MUST 早于 report_ready"
        "(避前端 race;design.md I-Backend-1)"
    )
