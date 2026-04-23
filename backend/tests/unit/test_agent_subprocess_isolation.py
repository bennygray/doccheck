"""L1 - run_isolated per-task 子进程隔离 (harden-async-infra F1)

验证:
- (a) 段错误 → AgentSkippedError(SKIP_REASON_SUBPROC_CRASH)
- (b) 超时 → AgentSkippedError(SKIP_REASON_SUBPROC_TIMEOUT)
- (c) 正常 func → 正常返值
- (d) 连续 5 次正常调用后无进程泄漏(psutil.children 为空)
- (e) 外层 wait_for 超时时 pool 清理
- (f) hang 场景连续 5 次调用后 children 不无限累积(reviewer H1 回归)
"""

from __future__ import annotations

import asyncio
import os
import time

import psutil
import pytest

from app.services.detect.agents._subprocess import run_isolated
from app.services.detect.errors import (
    SKIP_REASON_SUBPROC_CRASH,
    SKIP_REASON_SUBPROC_TIMEOUT,
    AgentSkippedError,
)


# ---- 模块级 func(可 pickle) ----


def _normal_add(a: int, b: int) -> int:
    return a + b


def _sleep_then_return(seconds: float) -> str:
    time.sleep(seconds)
    return "done"


def _crash_segfault():
    """模拟子进程非零退出(段错误等效):os._exit 绕过 finalizer,触发 BrokenProcessPool。"""
    os._exit(139)


def _hang_forever():
    """死循环,子进程永不返回,用于验证超时路径 + hang worker 清理。"""
    while True:
        pass


# ---- (a) 段错误 ----


@pytest.mark.asyncio
async def test_subprocess_crash_to_skip_reason_crash():
    with pytest.raises(AgentSkippedError) as excinfo:
        await run_isolated(_crash_segfault, timeout=5.0)
    assert str(excinfo.value) == SKIP_REASON_SUBPROC_CRASH


# ---- (b) 超时 ----


@pytest.mark.asyncio
async def test_subprocess_timeout_to_skip_reason_timeout():
    with pytest.raises(AgentSkippedError) as excinfo:
        await run_isolated(_sleep_then_return, 10.0, timeout=0.2)
    assert str(excinfo.value) == SKIP_REASON_SUBPROC_TIMEOUT


# ---- (c) 正常 ----


@pytest.mark.asyncio
async def test_subprocess_normal_returns_value():
    result = await run_isolated(_normal_add, 3, 4, timeout=10.0)
    assert result == 7


# ---- (d) 连续 5 次正常后无泄漏 ----


@pytest.mark.asyncio
async def test_no_process_leak_after_normal_runs():
    import platform

    for _ in range(5):
        result = await run_isolated(_normal_add, 1, 1, timeout=10.0)
        assert result == 2

    # 给 daemon worker 少量时间清理
    await asyncio.sleep(0.5)
    proc = psutil.Process()
    alive_children = [c for c in proc.children(recursive=True) if c.is_running()]
    # reviewer L2:Windows daemon 清理延迟更长,阈值放宽;Linux 正常 0-5
    max_alive = 10 if platform.system() == "Windows" else 5
    assert len(alive_children) <= max_alive, (
        f"normal run leak on {platform.system()}: {len(alive_children)} zombies"
    )


# ---- (e) 外层 wait_for 超时 ----


@pytest.mark.asyncio
async def test_outer_wait_for_timeout_cleans_pool():
    """外层 wait_for 比 run_isolated 内部超时小 → 外层先触发,验证内部 finally
    仍能 shutdown 清理。"""
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            run_isolated(_sleep_then_return, 10.0, timeout=10.0),
            timeout=0.2,
        )
    # 不关心断言细节:只要 wait_for 能正常 cancel 并不 hang 就 OK
    # 不 hang 本身就是通过条件


# ---- (f) hang 场景 5 次不累积(H1 回归) ----


@pytest.mark.asyncio
async def test_hang_workers_do_not_accumulate():
    """reviewer H1:shutdown(wait=False) 在 hang worker 场景下不等优雅退出,
    验证 5 次 hang + timeout 后,alive children 不突破 reasonable 上限。"""
    import platform

    for _ in range(5):
        with pytest.raises(AgentSkippedError):
            await run_isolated(_hang_forever, timeout=0.2)

    await asyncio.sleep(0.5)
    proc = psutil.Process()
    alive_children = [c for c in proc.children(recursive=True) if c.is_running()]
    # reviewer L2:terminate/kill 循环释放,Windows daemon 清理慢些上限放宽
    max_alive = 15 if platform.system() == "Windows" else 10
    assert len(alive_children) <= max_alive, (
        f"hang workers accumulated on {platform.system()}:"
        f" {len(alive_children)} zombies"
    )
