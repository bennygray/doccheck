"""检测 orchestrator (C6 detect-framework)

职责:
- `get_cpu_executor() / shutdown_cpu_executor()`:ProcessPoolExecutor 接口预留(C7+ 真 Agent 消费)
- `run_detection(project_id, version)`:顶层调度 — asyncio.gather 并发跑所有 AgentTask
- `_run_single_agent_task(agent_task_id)`:单 Agent 执行流程(preflight → wait_for run → status 更新 → broker publish)
- `INFRA_DISABLE_DETECT=1` 测试开关:仅创建 AgentTask 行,跳过 create_task

超时:
- AGENT_TIMEOUT_S  默认 300s;环境变量 AGENT_TIMEOUT_S 覆盖(L2 测试缩到秒级)
- GLOBAL_TIMEOUT_S 默认 1800s;环境变量 GLOBAL_TIMEOUT_S 覆盖
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.bidder import Bidder
from app.services.detect.context import AgentContext, PreflightResult
from app.services.detect.registry import AGENT_REGISTRY
from app.services.parser.pipeline.progress_broker import progress_broker

logger = logging.getLogger(__name__)


# ----- 超时常量(环境变量可覆盖,L2 测试会缩到秒级) --------------------
def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except ValueError:
        return default


# 模块级默认值(保留做兼容),但运行时通过 getter 动态读取以支持 monkeypatch
AGENT_TIMEOUT_S = _env_float("AGENT_TIMEOUT_S", 300.0)
GLOBAL_TIMEOUT_S = _env_float("GLOBAL_TIMEOUT_S", 1800.0)


def get_agent_timeout_s() -> float:
    return _env_float("AGENT_TIMEOUT_S", 300.0)


def get_global_timeout_s() -> float:
    return _env_float("GLOBAL_TIMEOUT_S", 1800.0)


def detect_disabled() -> bool:
    """动态读环境变量,便于测试用 monkeypatch。"""
    return os.environ.get("INFRA_DISABLE_DETECT") == "1"


# ----- ProcessPoolExecutor 接口预留 (D9) ---------------------------------
_CPU_EXECUTOR: ProcessPoolExecutor | None = None


def get_cpu_executor() -> ProcessPoolExecutor:
    """Lazy 单例。C6 dummy 不用;C7+ 真 CPU Agent 调 run_in_executor 消费。"""
    global _CPU_EXECUTOR
    if _CPU_EXECUTOR is None:
        workers = os.cpu_count() or 2
        _CPU_EXECUTOR = ProcessPoolExecutor(max_workers=workers)
    return _CPU_EXECUTOR


def shutdown_cpu_executor() -> None:
    """FastAPI shutdown 时释放资源。"""
    global _CPU_EXECUTOR
    if _CPU_EXECUTOR is not None:
        _CPU_EXECUTOR.shutdown(wait=False, cancel_futures=True)
        _CPU_EXECUTOR = None


# ----- 核心调度 -----------------------------------------------------------
async def run_detection(project_id: int, version: int) -> None:
    """顶层 orchestrator。协程内部新建 session。

    被 `asyncio.create_task(run_detection(pid, v))` 启动;异常不暴露外层。
    """
    logger.info("detect: run_detection start project=%s v=%s", project_id, version)
    try:
        # 加载本轮所有 AgentTask id
        async with async_session() as session:
            stmt = select(AgentTask.id).where(
                AgentTask.project_id == project_id,
                AgentTask.version == version,
            )
            task_ids = [row for (row,) in (await session.execute(stmt)).all()]

        if not task_ids:
            logger.warning(
                "detect: no AgentTask rows for project=%s v=%s", project_id, version
            )
            return

        coros = [_run_single_agent_task(tid) for tid in task_ids]

        try:
            await asyncio.wait_for(
                asyncio.gather(*coros, return_exceptions=True),
                timeout=get_global_timeout_s(),
            )
        except TimeoutError:
            logger.warning(
                "detect: global timeout project=%s v=%s", project_id, version
            )
            await _mark_all_running_as_timeout(project_id, version)

        # C17: 检测前读取 SystemConfig 规则配置
        from app.services.admin.rules_mapper import config_to_engine_params
        from app.services.admin.rules_reader import get_active_rules

        async with async_session() as _rules_session:
            rules_config = await get_active_rules(_rules_session)
        engine_params = config_to_engine_params(rules_config)

        # 无论是否超时,都走研判(延迟导入避免循环依赖)
        from app.services.detect.judge import judge_and_create_report

        await judge_and_create_report(
            project_id, version, rules_config=engine_params
        )

    except Exception as exc:  # noqa: BLE001 - 顶层兜底
        logger.exception(
            "detect: run_detection crash project=%s v=%s: %s",
            project_id,
            version,
            exc,
        )
    finally:
        logger.info("detect: run_detection end project=%s v=%s", project_id, version)


async def _run_single_agent_task(agent_task_id: int) -> None:
    """单 Agent 执行。外层用 `async with track(...)` 包裹心跳。"""
    # 延迟导入避免循环依赖(async_tasks.tracker → detect.engine 潜在环路)
    from app.services.async_tasks.tracker import track

    async with track(
        subtype="agent_run",
        entity_type="agent_task",
        entity_id=agent_task_id,
    ):
        await _execute_agent_task(agent_task_id)


async def _execute_agent_task(agent_task_id: int) -> None:
    """读 AgentTask → preflight → run → 更新状态 + publish SSE。

    不在 track 外因为 track 异常重抛,单 Agent 异常不应导致 track 失败(
    Agent 业务异常我们自己写进 AgentTask.error,track 标 done 是对的)。
    """
    async with async_session() as session:
        task: AgentTask | None = await session.get(AgentTask, agent_task_id)
        if task is None:
            logger.warning("detect: agent_task %s vanished", agent_task_id)
            return

        spec = AGENT_REGISTRY.get(task.agent_name)
        if spec is None:
            await _mark_failed(
                session, task, f"agent not registered: {task.agent_name}"
            )
            await session.commit()
            await _publish_agent_status(task)
            return

        # 构造 ctx
        ctx = await _build_ctx(session, task)

        # status=running + started_at
        task.status = "running"
        task.started_at = datetime.now(UTC)
        await session.commit()
        await _publish_agent_status(task)

        # preflight
        try:
            pf: PreflightResult = await spec.preflight(ctx)
        except Exception as exc:  # noqa: BLE001
            await _mark_skipped(
                session, task, f"preflight 异常: {type(exc).__name__}: {exc}"
            )
            await session.commit()
            await _publish_agent_status(task)
            return

        if pf.status == "skip":
            await _mark_skipped(session, task, pf.reason or "skipped")
            await session.commit()
            await _publish_agent_status(task)
            return

        if pf.status == "downgrade":
            ctx.downgrade = True

        # run with timeout
        try:
            result = await asyncio.wait_for(spec.run(ctx), timeout=get_agent_timeout_s())
        except TimeoutError:
            await _mark_timeout(session, task)
            await session.commit()
            await _publish_agent_status(task)
            return
        except Exception as exc:  # noqa: BLE001
            await _mark_failed(
                session, task, f"{type(exc).__name__}: {exc}"
            )
            await session.commit()
            await _publish_agent_status(task)
            return

        await _mark_succeeded(session, task, result.score, result.summary)
        await session.commit()
        await _publish_agent_status(task)


async def _build_ctx(session: AsyncSession, task: AgentTask) -> AgentContext:
    bidder_a = (
        await session.get(Bidder, task.pair_bidder_a_id)
        if task.pair_bidder_a_id
        else None
    )
    bidder_b = (
        await session.get(Bidder, task.pair_bidder_b_id)
        if task.pair_bidder_b_id
        else None
    )
    # global 型需要 all_bidders
    all_bidders: list[Bidder] = []
    if task.agent_type == "global":
        stmt = select(Bidder).where(
            Bidder.project_id == task.project_id,
            Bidder.deleted_at.is_(None),
        )
        all_bidders = list((await session.execute(stmt)).scalars().all())

    # C7: text_similarity 起需要真实 llm_provider;C6 dummy Agent 不触 LLM 字段
    # 测试通过 monkeypatch app.services.llm.factory._build_default_provider 注入 mock
    # 读失败(未配 API key / env)时 provider=None,Agent 自然进降级分支
    from app.services.llm import get_llm_provider

    try:
        llm_provider = get_llm_provider()
    except Exception:  # noqa: BLE001 - LLM 未配置不应 crash 检测流程
        llm_provider = None

    return AgentContext(
        project_id=task.project_id,
        version=task.version,
        agent_task=task,
        bidder_a=bidder_a,
        bidder_b=bidder_b,
        all_bidders=all_bidders,
        llm_provider=llm_provider,
        session=session,
        downgrade=False,
    )


# ----- status 变更 helpers ------------------------------------------------
def _elapsed_ms(task: AgentTask) -> int:
    if task.started_at is None:
        return 0
    now = datetime.now(UTC)
    started = task.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return max(0, int((now - started).total_seconds() * 1000))


async def _mark_succeeded(
    session: AsyncSession, task: AgentTask, score: float, summary: str
) -> None:
    task.status = "succeeded"
    task.score = Decimal(str(round(score, 2)))
    task.summary = (summary or "")[:500]
    task.finished_at = datetime.now(UTC)
    task.elapsed_ms = _elapsed_ms(task)


async def _mark_skipped(
    session: AsyncSession, task: AgentTask, reason: str
) -> None:
    task.status = "skipped"
    task.summary = reason[:500]
    task.finished_at = datetime.now(UTC)
    task.elapsed_ms = _elapsed_ms(task) if task.started_at else 0


async def _mark_failed(
    session: AsyncSession, task: AgentTask, error: str
) -> None:
    task.status = "failed"
    task.error = error[:500]
    task.finished_at = datetime.now(UTC)
    task.elapsed_ms = _elapsed_ms(task)


async def _mark_timeout(session: AsyncSession, task: AgentTask) -> None:
    task.status = "timeout"
    task.summary = f"Agent 超时 (>{int(get_agent_timeout_s())}s)"
    task.finished_at = datetime.now(UTC)
    task.elapsed_ms = _elapsed_ms(task)


async def _mark_all_running_as_timeout(project_id: int, version: int) -> None:
    """全局超时兜底:把所有 running / pending 的 AgentTask 标 timeout。"""
    async with async_session() as session:
        stmt = (
            update(AgentTask)
            .where(
                AgentTask.project_id == project_id,
                AgentTask.version == version,
                AgentTask.status.in_(("running", "pending")),
            )
            .values(
                status="timeout",
                summary="Agent 超时 (全局)",
                finished_at=datetime.now(UTC),
            )
        )
        await session.execute(stmt)
        await session.commit()


# ----- SSE publish --------------------------------------------------------
async def _publish_agent_status(task: AgentTask) -> None:
    """推送 agent_status 事件到 progress_broker。"""
    data: dict[str, Any] = {
        "version": task.version,
        "agent_task_id": task.id,
        "agent_name": task.agent_name,
        "agent_type": task.agent_type,
        "pair": (
            {"a": task.pair_bidder_a_id, "b": task.pair_bidder_b_id}
            if task.agent_type == "pair"
            else None
        ),
        "status": task.status,
        "score": float(task.score) if task.score is not None else None,
        "summary": task.summary,
        "elapsed_ms": task.elapsed_ms,
    }
    await progress_broker.publish(task.project_id, "agent_status", data)


__all__ = [
    "AGENT_TIMEOUT_S",
    "GLOBAL_TIMEOUT_S",
    "detect_disabled",
    "get_cpu_executor",
    "shutdown_cpu_executor",
    "run_detection",
]
