"""L2 - AgentSkippedError → engine → judge 端到端集成 (harden-async-infra 2.11~2.14)

实测策略:monkeypatch SIGNAL_AGENTS agent 的 `run()` 直接 raise AgentSkippedError,
验证端到端集成:
- engine._execute_agent_task 捕获 AgentSkippedError → _mark_skipped
- AgentTask.status=skipped + summary 为中文常量文案
- 其他 agent 不受影响,并行跑完
- 多 agent 全 skipped 时,judge.judge_and_create_report 走 indeterminate +
  INSUFFICIENT_EVIDENCE_CONCLUSION(honest-detection-results 已建立的 SIGNAL_AGENTS
  证据不足路径)

绕开真实 subprocess 路径 — run_isolated 的 subprocess 崩溃/超时已由 L1
`test_agent_subprocess_isolation.py` 6 case 覆盖(含 hang 回归);此处 L2 聚焦
"AgentSkippedError 信号能正确贯穿 engine + judge" 这一集成契约。
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
from app.services.detect.context import AgentRunResult
from app.services.detect.errors import (
    SKIP_REASON_LLM_TIMEOUT,
    SKIP_REASON_SUBPROC_CRASH,
    SKIP_REASON_SUBPROC_TIMEOUT,
    AgentSkippedError,
)
from app.services.detect.registry import AGENT_REGISTRY

pytestmark = pytest.mark.asyncio


async def _seed(owner_id: int, n: int = 2) -> int:
    async with async_session() as s:
        p = Project(name="p-f1l2", status="ready", owner_id=owner_id)
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
    raise AssertionError(f"AnalysisReport not ready in {timeout}s")


async def _get_tasks(pid: int) -> list[AgentTask]:
    async with async_session() as s:
        return list((
            await s.execute(select(AgentTask).where(AgentTask.project_id == pid))
        ).scalars().all())


def _replace_run(monkeypatch, agent_name: str, new_run):
    """把 registry 中某 agent 的 run() 替换为 new_run(保留 preflight)。"""
    monkeypatch.setitem(
        AGENT_REGISTRY,
        agent_name,
        AGENT_REGISTRY[agent_name]._replace(
            run=new_run,
            # 把 preflight 强制成 ok,避免"缺少可对比文档"提前 skip
            preflight=_always_ok_preflight,
        ),
    )


async def _always_ok_preflight(ctx):
    from app.services.detect.context import PreflightResult
    return PreflightResult("ok")


# ========== 2.11:AgentSkippedError(crash reason) → skipped + summary ==========


async def test_agent_skipped_subproc_crash_end_to_end(
    seeded_reviewer: User, reviewer_token, auth_client, monkeypatch
):
    """某 agent.run() raise AgentSkippedError("解析崩溃,已跳过") → 该 agent
    task.status=skipped + summary=常量字符串;其他 agent 正常跑完。"""
    monkeypatch.delenv("INFRA_DISABLE_DETECT", raising=False)
    monkeypatch.setenv("AGENT_TIMEOUT_S", "5")
    monkeypatch.setenv("GLOBAL_TIMEOUT_S", "30")

    async def _raise_crash(_ctx):
        raise AgentSkippedError(SKIP_REASON_SUBPROC_CRASH)

    _replace_run(monkeypatch, "text_similarity", _raise_crash)

    pid = await _seed(seeded_reviewer.id, n=2)
    client = await auth_client(reviewer_token)
    resp = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp.status_code == 201

    await _wait_for_report(pid)
    tasks = await _get_tasks(pid)

    text_sim_tasks = [t for t in tasks if t.agent_name == "text_similarity"]
    assert len(text_sim_tasks) >= 1
    for t in text_sim_tasks:
        assert t.status == "skipped", f"expected skipped, got {t.status}"
        assert t.summary == SKIP_REASON_SUBPROC_CRASH, (
            f"summary should equal SKIP_REASON_SUBPROC_CRASH,"
            f" got {t.summary!r}"
        )

    others_succeeded = [
        t for t in tasks
        if t.agent_name != "text_similarity" and t.status == "succeeded"
    ]
    assert len(others_succeeded) >= 1, (
        f"non-text_similarity agents should complete: "
        f"{[(t.agent_name, t.status) for t in tasks]}"
    )


# ========== 2.12:AgentSkippedError(timeout reason) → skipped + 不同 summary ==========


async def test_agent_skipped_subproc_timeout_end_to_end(
    seeded_reviewer: User, reviewer_token, auth_client, monkeypatch
):
    """section_similarity.run() raise AgentSkippedError("解析超时,已跳过") →
    status=skipped + summary 精确对齐常量。"""
    monkeypatch.delenv("INFRA_DISABLE_DETECT", raising=False)
    monkeypatch.setenv("AGENT_TIMEOUT_S", "5")
    monkeypatch.setenv("GLOBAL_TIMEOUT_S", "30")

    async def _raise_timeout(_ctx):
        raise AgentSkippedError(SKIP_REASON_SUBPROC_TIMEOUT)

    _replace_run(monkeypatch, "section_similarity", _raise_timeout)

    pid = await _seed(seeded_reviewer.id, n=2)
    client = await auth_client(reviewer_token)
    resp = await client.post(f"/api/projects/{pid}/analysis/start")
    assert resp.status_code == 201

    await _wait_for_report(pid)
    tasks = await _get_tasks(pid)

    section_tasks = [t for t in tasks if t.agent_name == "section_similarity"]
    assert len(section_tasks) >= 1
    for t in section_tasks:
        assert t.status == "skipped"
        assert t.summary == SKIP_REASON_SUBPROC_TIMEOUT


# ========== 2.13:structure_similarity 对称行为 ==========


async def test_structure_similarity_skipped_error_symmetric(
    seeded_reviewer: User, reviewer_token, auth_client, monkeypatch
):
    """structure_similarity.run() raise AgentSkippedError 同样走 skipped。"""
    monkeypatch.delenv("INFRA_DISABLE_DETECT", raising=False)
    monkeypatch.setenv("AGENT_TIMEOUT_S", "5")
    monkeypatch.setenv("GLOBAL_TIMEOUT_S", "30")

    async def _raise_crash(_ctx):
        raise AgentSkippedError(SKIP_REASON_SUBPROC_CRASH)

    _replace_run(monkeypatch, "structure_similarity", _raise_crash)

    pid = await _seed(seeded_reviewer.id, n=2)
    client = await auth_client(reviewer_token)
    await client.post(f"/api/projects/{pid}/analysis/start")
    await _wait_for_report(pid)

    tasks = await _get_tasks(pid)
    struct_tasks = [t for t in tasks if t.agent_name == "structure_similarity"]
    assert len(struct_tasks) >= 1
    for t in struct_tasks:
        assert t.status == "skipped"
        assert t.summary == SKIP_REASON_SUBPROC_CRASH


# ========== 2.14:所有 SIGNAL_AGENTS skipped → judge indeterminate ==========


async def test_all_signal_agents_skipped_judge_indeterminate(
    seeded_reviewer: User, reviewer_token, auth_client, monkeypatch
):
    """把所有 SIGNAL_AGENTS(6 个)的 run() 全部替换为 raise AgentSkippedError;
    judge._has_sufficient_evidence 应返 False,report.risk_level=indeterminate +
    llm_conclusion 为 INSUFFICIENT_EVIDENCE_CONCLUSION。"""
    monkeypatch.delenv("INFRA_DISABLE_DETECT", raising=False)
    monkeypatch.setenv("AGENT_TIMEOUT_S", "5")
    monkeypatch.setenv("GLOBAL_TIMEOUT_S", "30")

    from app.services.detect.judge_llm import (
        INSUFFICIENT_EVIDENCE_CONCLUSION,
        SIGNAL_AGENTS,
    )

    async def _raise_llm_timeout(_ctx):
        raise AgentSkippedError(SKIP_REASON_LLM_TIMEOUT)

    for agent_name in SIGNAL_AGENTS:
        if agent_name in AGENT_REGISTRY:
            _replace_run(monkeypatch, agent_name, _raise_llm_timeout)

    pid = await _seed(seeded_reviewer.id, n=2)
    client = await auth_client(reviewer_token)
    await client.post(f"/api/projects/{pid}/analysis/start")
    report = await _wait_for_report(pid)

    assert report.risk_level == "indeterminate", (
        f"expected indeterminate, got {report.risk_level}"
    )
    assert report.llm_conclusion == INSUFFICIENT_EVIDENCE_CONCLUSION, (
        f"expected INSUFFICIENT_EVIDENCE_CONCLUSION,"
        f" got {report.llm_conclusion!r}"
    )

    tasks = await _get_tasks(pid)
    signal_skipped = [
        t for t in tasks
        if t.agent_name in SIGNAL_AGENTS and t.status == "skipped"
    ]
    assert len(signal_skipped) >= 1, (
        f"at least one signal agent should be skipped,"
        f" got: {[(t.agent_name, t.status) for t in tasks]}"
    )
    for t in signal_skipped:
        assert t.summary == SKIP_REASON_LLM_TIMEOUT
