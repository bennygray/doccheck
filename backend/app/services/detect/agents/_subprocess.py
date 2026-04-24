"""per-task 子进程隔离 helper (harden-async-infra F1 / D1)

核心函数 `run_isolated(func, *args, timeout)`:
- 起**一次性** ProcessPoolExecutor(max_workers=1) 跑 func(可 pickle)
- `asyncio.wait_for` 包 `asyncio.wrap_future`,到 timeout 或 pool broken 立即抛
- `asyncio.TimeoutError` → `AgentSkippedError(SKIP_REASON_SUBPROC_TIMEOUT)`
- `BrokenProcessPool`(段错误 / OOM / 非零退出) → `AgentSkippedError(SKIP_REASON_SUBPROC_CRASH)`
- **不**用 `with` context manager,因为 `__exit__` 默认 `shutdown(wait=True)` 在 hang
  worker 场景会一并卡住;改 `try/finally: shutdown(wait=False, cancel_futures=True)`。

替代共享 `get_cpu_executor()` singleton 的使用:
- section_similarity / text_similarity / structure_similarity 三个 CPU 密集 agent
  原先 `loop.run_in_executor(get_cpu_executor(), func, *args)` 改为 `await run_isolated(...)`
- 坏 docx 触发 worker 段错误不再把共享 pool 拉坏影响其他投标人
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import TypeVar

from app.services.detect.errors import (
    SKIP_REASON_SUBPROC_CRASH,
    SKIP_REASON_SUBPROC_TIMEOUT,
    AgentSkippedError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def run_isolated(
    func: Callable[..., T],
    /,
    *args: object,
    timeout: float,
) -> T:
    """在隔离子进程里跑 func(*args),超时 / 崩溃 → `AgentSkippedError`。

    Args:
        func: 可 pickle 的同步函数(CPU 密集)
        *args: 可 pickle 的参数
        timeout: 秒,超过即抛 `AgentSkippedError(SKIP_REASON_SUBPROC_TIMEOUT)`

    Returns:
        func 的返回值

    Raises:
        AgentSkippedError: subprocess 崩溃或超时;其他异常(正常返的 func 里抛的)
                           会原样重抛,由 agent 或 engine 处理
    """
    pool = ProcessPoolExecutor(max_workers=1)
    try:
        # 走 loop.run_in_executor 而非直接 pool.submit,以保留测试层
        # monkeypatch `asyncio.get_running_loop().run_in_executor` 的同步拦截能力。
        # 生产环境:真实 loop 会 pool.submit(func, *args) 在独立 worker 进程跑。
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(pool, func, *args)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            logger.warning(
                "run_isolated: subprocess timeout func=%s timeout=%ss",
                getattr(func, "__name__", repr(func)),
                timeout,
            )
            raise AgentSkippedError(SKIP_REASON_SUBPROC_TIMEOUT) from None
        except BrokenProcessPool as exc:
            logger.warning(
                "run_isolated: subprocess broken func=%s exc=%s",
                getattr(func, "__name__", repr(func)),
                exc,
            )
            raise AgentSkippedError(SKIP_REASON_SUBPROC_CRASH) from None
    finally:
        # reviewer H1 的核心修复:shutdown(wait=False) 不会中断 worker 内已在跑的
        # hang 任务(while True 等)。必须主动 terminate / kill 该 worker,否则
        # zombie 进程累积占 CPU 直到父进程退出。
        #
        # ProcessPoolExecutor._processes 是官方 stdlib 属性(字典 pid→Process),
        # 虽为下划线前缀但 Py 3.8~3.13 稳定可用,作为"per-call 池"无 race 风险。
        #
        # test-infra-followup-wave2 Item 3:对 Py 3.14+ 潜在字段消失 / 类型变化
        # (例如改 method / 改容器类型)加 try/except 兜底。fallback 路径 = 纯
        # shutdown(wait=False) 无主动 terminate/kill,假定届时 stdlib 已完备清理
        # hang worker(3.13 及之前不会触发 fallback)。
        try:
            workers = list(getattr(pool, "_processes", {}).values())
        except (AttributeError, TypeError) as exc:
            logger.warning(
                "run_isolated: _processes 访问异常,走 fallback shutdown(%s)", exc
            )
            workers = []
        pool.shutdown(wait=False, cancel_futures=True)
        for proc in workers:
            try:
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=0.3)
                    if proc.is_alive():
                        proc.kill()
                        proc.join(timeout=0.3)
            except Exception as exc:  # noqa: BLE001 - 清理路径不抛
                logger.warning("run_isolated worker kill failed: %s", exc)


__all__ = ["run_isolated"]
