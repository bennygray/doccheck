"""L2 - LLM 超时端到端 (harden-async-infra 3.11)

验证:
- style agent 的 LLM stage 失败 → style task skipped + summary="LLM 超时,已跳过"
- 若仅 style skipped(其他信号 agent 正常运行):judge 正常走 LLM / fallback 路径;
  report 正常落库 + report_ready=true(不一定 indeterminate,因其他信号充分)
"""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.bidder import Bidder
from app.models.project import Project
from app.models.user import User
from app.services.detect.errors import SKIP_REASON_LLM_TIMEOUT

pytestmark = pytest.mark.asyncio


async def _seed(owner_id: int, n: int = 2) -> int:
    async with async_session() as s:
        p = Project(name="p-n7l2", status="ready", owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        for i in range(n):
            s.add(
                Bidder(
                    name=f"B{i}",
                    project_id=p.id,
                    parse_status="identified",
                    identity_info={"x": i},
                )
            )
        await s.commit()
        return p.id


async def _wait_for_report(pid: int, timeout: float = 30.0) -> AnalysisReport:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        async with async_session() as s:
            report = (
                await s.execute(
                    select(AnalysisReport).where(AnalysisReport.project_id == pid)
                )
            ).scalar_one_or_none()
            if report is not None:
                return report
        await asyncio.sleep(0.3)
    raise AssertionError("AnalysisReport not ready")


async def test_style_llm_timeout_marks_skipped(
    seeded_reviewer: User, reviewer_token, auth_client, monkeypatch
):
    """让 style agent 的 LLM client 全部重试失败 → style.run() 抛
    AgentSkippedError(LLM 超时),engine 标 skipped,summary=常量。"""
    monkeypatch.delenv("INFRA_DISABLE_DETECT", raising=False)
    monkeypatch.setenv("AGENT_TIMEOUT_S", "5")
    monkeypatch.setenv("GLOBAL_TIMEOUT_S", "30")

    # 直接让 style.run() 模拟 LLM 耗尽重试的典型产物 — raise AgentSkippedError
    # 这等价于 style_impl/llm_client._call_with_retry_and_parse 所有重试超时后的
    # raise 路径被 style.py 的 except AgentSkippedError: raise 透传到 engine
    from app.services.detect.context import PreflightResult
    from app.services.detect.errors import AgentSkippedError
    from app.services.detect.registry import AGENT_REGISTRY

    async def _always_ok(_ctx):
        return PreflightResult("ok")

    async def _raise_llm_timeout(_ctx):
        raise AgentSkippedError(SKIP_REASON_LLM_TIMEOUT)

    monkeypatch.setitem(
        AGENT_REGISTRY,
        "style",
        AGENT_REGISTRY["style"]._replace(
            preflight=_always_ok, run=_raise_llm_timeout
        ),
    )

    pid = await _seed(seeded_reviewer.id, n=2)
    client = await auth_client(reviewer_token)
    resp = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp.status_code == 201

    report = await _wait_for_report(pid)
    # report 正常落库
    assert report is not None

    async with async_session() as s:
        style_tasks = list(
            (
                await s.execute(
                    select(AgentTask).where(
                        AgentTask.project_id == pid,
                        AgentTask.agent_name == "style",
                    )
                )
            ).scalars().all()
        )

    assert len(style_tasks) >= 1
    for t in style_tasks:
        assert t.status == "skipped", (
            f"style should be skipped on LLM timeout, got {t.status}"
        )
        assert t.summary == SKIP_REASON_LLM_TIMEOUT, (
            f"summary should equal SKIP_REASON_LLM_TIMEOUT,"
            f" got {t.summary!r}"
        )


async def test_report_ready_true_after_llm_timeout_with_other_signals(
    seeded_reviewer: User, reviewer_token, auth_client, monkeypatch
):
    """仅 style skipped 不应阻塞 report 落库;report_ready=true 的 API 语义不变。"""
    monkeypatch.delenv("INFRA_DISABLE_DETECT", raising=False)
    monkeypatch.setenv("AGENT_TIMEOUT_S", "5")
    monkeypatch.setenv("GLOBAL_TIMEOUT_S", "30")

    from app.services.detect.context import PreflightResult
    from app.services.detect.errors import AgentSkippedError
    from app.services.detect.registry import AGENT_REGISTRY

    async def _always_ok(_ctx):
        return PreflightResult("ok")

    async def _raise_llm_timeout(_ctx):
        raise AgentSkippedError(SKIP_REASON_LLM_TIMEOUT)

    monkeypatch.setitem(
        AGENT_REGISTRY,
        "style",
        AGENT_REGISTRY["style"]._replace(
            preflight=_always_ok, run=_raise_llm_timeout
        ),
    )

    pid = await _seed(seeded_reviewer.id, n=2)
    client = await auth_client(reviewer_token)
    await client.post(f"/api/projects/{pid}/analysis/start")
    await _wait_for_report(pid)

    # 查询 /analysis/status 断言 report_ready=true
    status_resp = await client.get(f"/api/projects/{pid}/analysis/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data.get("report_ready") is True, (
        f"report_ready should be true after style LLM timeout,"
        f" got {status_data}"
    )
