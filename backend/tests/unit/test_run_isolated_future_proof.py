"""L1 - run_isolated 对 ProcessPoolExecutor._processes 内部字段变化的 future-proof
(test-infra-followup-wave2 Item 3)。

harden-async-infra D1 的 `run_isolated` finally 块依赖 `pool._processes`(stdlib
下划线字段)主动 terminate/kill hang worker。Py 3.14+ 若把 `_processes` 改成 method /
删除 / 容器变 list,`getattr(...).values()` 会抛 AttributeError/TypeError。

**测试策略**:
- 静态断言(source-level):确保 `_processes` 访问被 try/except (AttributeError, TypeError)
  兜底,且 fallback 是纯 shutdown 路径
- happy-path 实跑:在 Py ≤3.13 真实 pool 下跑 run_isolated,确认零回归

不用 mock 注入 _processes 异常,因为 stdlib 自身在 pool 运行期需读 _processes
(`_adjust_process_count`),mock 会破坏 pool 本体而不是测 finally 块。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.detect.agents import _subprocess as subprocess_mod
from app.services.detect.agents._subprocess import run_isolated


_SRC_PATH = Path(subprocess_mod.__file__)


# ------------------------------------------------------------ 静态源码断言


def test_run_isolated_has_try_except_around_processes_access():
    """finally 块里 `_processes` 访问必须被 try/except (AttributeError, TypeError) 包住。"""
    src = _SRC_PATH.read_text(encoding="utf-8")
    # 期望出现 try block 里 getattr(pool, "_processes", ...),
    # except 明确列出 AttributeError 和 TypeError
    assert re.search(
        r"try:\s*\n\s*workers\s*=\s*list\(getattr\(pool,\s*['\"]_processes['\"]",
        src,
    ), "finally 块未把 _processes 访问放进 try 守卫"
    assert "except (AttributeError, TypeError)" in src, (
        "finally 块未 except (AttributeError, TypeError) 兜 stdlib 字段变动"
    )


def test_run_isolated_fallback_path_skips_terminate():
    """fallback(_processes 异常)时 workers=[] → for 循环零迭代 → 纯 shutdown 路径。"""
    src = _SRC_PATH.read_text(encoding="utf-8")
    # 关键结构:fallback 后 workers 赋空 list,随后统一 for 循环;source 里看到
    # "workers = []" 在 except 块里
    assert re.search(
        r"except\s*\(\s*AttributeError\s*,\s*TypeError\s*\)[^\n]*\n(?:[^\n]*\n){0,4}?\s*workers\s*=\s*\[\]",
        src,
    ), "fallback 路径应赋 workers=[](空 list),让 for 循环零迭代走纯 shutdown"


def test_run_isolated_still_calls_shutdown_wait_false():
    """主路径和 fallback 路径都必须调 `shutdown(wait=False, cancel_futures=True)`。"""
    src = _SRC_PATH.read_text(encoding="utf-8")
    assert "shutdown(wait=False, cancel_futures=True)" in src, (
        "run_isolated finally 未调 shutdown(wait=False, cancel_futures=True)"
    )


# ------------------------------------------------------------ 实跑 happy path


def _noop() -> int:
    return 42


@pytest.mark.asyncio
async def test_run_isolated_happy_path():
    """baseline:正常 run_isolated 返回 func 结果,Py ≤3.13 下 _processes 走完整清理路径。"""
    result = await run_isolated(_noop, timeout=10.0)
    assert result == 42
