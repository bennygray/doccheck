"""L2: detect/engine.run_detection 端到端编排 (C6 §11.7)

关闭 INFRA_DISABLE_DETECT,缩短超时到秒级,验证:
- 10 AgentTask 全部走完 → AnalysisReport 落地
- 单 Agent 异常隔离
- 全局超时标未完成为 timeout,仍生成报告
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.bidder import Bidder
from app.models.project import Project
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _seed(owner_id: int, n: int = 2) -> int:
    async with async_session() as s:
        p = Project(name="p", status="ready", owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        for i in range(n):
            s.add(
                Bidder(
                    name=f"B{i}",
                    project_id=p.id,
                    parse_status="identified",
                    identity_info={"x": i},  # error_consistency 不降级
                )
            )
        await s.commit()
        return p.id


async def test_run_detection_happy_path(
    seeded_reviewer: User, reviewer_token, auth_client, monkeypatch
):
    """完整跑完 11 AgentTask + 生成 AnalysisReport + project 进 completed (C12)。"""
    monkeypatch.delenv("INFRA_DISABLE_DETECT", raising=False)
    # 缩短超时到秒级
    monkeypatch.setenv("AGENT_TIMEOUT_S", "5")
    monkeypatch.setenv("GLOBAL_TIMEOUT_S", "30")
    # 心跳缩到 0.5s(tracker 快速更新)
    monkeypatch.setenv("ASYNC_TASK_HEARTBEAT_S", "0.5")

    pid = await _seed(seeded_reviewer.id, n=2)
    client = await auth_client(reviewer_token)
    resp = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp.status_code == 201

    # 轮询等待 AnalysisReport 落地,最多 20s
    import time

    started = time.monotonic()
    while time.monotonic() - started < 30:
        async with async_session() as s:
            report = (
                await s.execute(
                    select(AnalysisReport).where(
                        AnalysisReport.project_id == pid
                    )
                )
            ).scalar_one_or_none()
            if report is not None:
                break
        await asyncio.sleep(0.5)

    assert report is not None, "AnalysisReport should be created"

    async with async_session() as s:
        # 所有 AgentTask 进终态
        tasks = (
            await s.execute(
                select(AgentTask).where(AgentTask.project_id == pid)
            )
        ).scalars().all()
        assert len(tasks) == 11
        assert all(
            t.status in ("succeeded", "failed", "timeout", "skipped")
            for t in tasks
        )
        # project 进 completed
        project = await s.get(Project, pid)
        assert project.status == "completed"


async def test_run_detection_agent_timeout(
    seeded_reviewer: User, reviewer_token, auth_client, monkeypatch
):
    """AGENT_TIMEOUT_S=0.05 → dummy Agent sleep 0.2-1.0s 必然超时。"""
    monkeypatch.delenv("INFRA_DISABLE_DETECT", raising=False)
    monkeypatch.setenv("AGENT_TIMEOUT_S", "0.05")
    monkeypatch.setenv("GLOBAL_TIMEOUT_S", "30")

    pid = await _seed(seeded_reviewer.id, n=2)
    client = await auth_client(reviewer_token)
    await client.post(f"/api/projects/{pid}/analysis/start")

    import time

    started = time.monotonic()
    while time.monotonic() - started < 20:
        async with async_session() as s:
            report = (
                await s.execute(
                    select(AnalysisReport).where(
                        AnalysisReport.project_id == pid
                    )
                )
            ).scalar_one_or_none()
            if report is not None:
                break
        await asyncio.sleep(0.3)

    assert report is not None

    async with async_session() as s:
        tasks = (
            await s.execute(
                select(AgentTask).where(AgentTask.project_id == pid)
            )
        ).scalars().all()
        # 至少有一些 timeout(预期大部分都 timeout)
        timeout_count = sum(1 for t in tasks if t.status == "timeout")
        assert timeout_count > 0
