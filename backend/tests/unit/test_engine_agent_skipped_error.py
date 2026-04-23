"""L1 - engine 对 AgentSkippedError 的捕获顺序 (harden-async-infra D2)

核心约束:`except AgentSkippedError` MUST 出现在 `except Exception` **之前**,
否则通用 Exception 分支会吞掉 AgentSkippedError → 走 _mark_failed (status="failed")
而非 _mark_skipped (status="skipped")。

完整行为验证(AgentSkippedError → skipped / RuntimeError → failed)见 L2
`test_detect_subprocess_isolation.py`。此处 L1 只做源码级顺序校验,不需 DB。
"""

from __future__ import annotations

from pathlib import Path

import app.services.detect.engine as engine_mod


import re


def _extract_code_lines(src: str) -> list[str]:
    """去掉 # 注释部分(保留 # 前的代码),方便按代码句子校验。"""
    lines = []
    for ln in src.splitlines():
        # 粗略去注释:第一个 # 后全部丢(不严谨但本测试用途足够)
        idx = ln.find("#")
        if idx >= 0:
            ln = ln[:idx]
        lines.append(ln)
    return lines


# 代码层级的 except 关键字行:开头为空白 + "except "
_EXCEPT_LINE_RE = re.compile(r"^\s*except\s+(\S+?)[\s(:]")


def test_engine_except_order_agent_skipped_before_exception():
    """engine._execute_agent_task 的 run() 分支里,AgentSkippedError 必须在紧随
    其后的 Exception 之前捕获(紧跟 AgentSkippedError 的代码级 except 就是 Exception)。
    """
    src = Path(engine_mod.__file__).read_text(encoding="utf-8")
    code_lines = _extract_code_lines(src)

    skipped_line_idx: int | None = None
    for i, ln in enumerate(code_lines):
        if "except AgentSkippedError" in ln:
            skipped_line_idx = i
            break
    assert skipped_line_idx is not None, "engine.py MUST 捕获 AgentSkippedError"

    # 从 AgentSkippedError 行之后找下一个代码级 except
    next_exc_type: str | None = None
    for j in range(skipped_line_idx + 1, len(code_lines)):
        m = _EXCEPT_LINE_RE.match(code_lines[j])
        if m:
            next_exc_type = m.group(1)
            break
    assert next_exc_type == "Exception", (
        "AgentSkippedError 紧跟的下一个代码级 except 必须是 `except Exception`,"
        f"实际:{next_exc_type!r}"
    )


def test_engine_skipped_branch_calls_mark_skipped():
    """AgentSkippedError 分支 body 必须调 `_mark_skipped`(不是 _mark_failed)。"""
    src = Path(engine_mod.__file__).read_text(encoding="utf-8")
    code_lines = _extract_code_lines(src)

    skipped_line_idx: int | None = None
    for i, ln in enumerate(code_lines):
        if "except AgentSkippedError" in ln:
            skipped_line_idx = i
            break
    assert skipped_line_idx is not None

    # 从 AgentSkippedError 行后到下一个代码级 except 行前,作为 block
    next_except_idx: int | None = None
    for j in range(skipped_line_idx + 1, len(code_lines)):
        if _EXCEPT_LINE_RE.match(code_lines[j]):
            next_except_idx = j
            break
    assert next_except_idx is not None

    block = "\n".join(code_lines[skipped_line_idx:next_except_idx])
    assert "_mark_skipped" in block, (
        f"AgentSkippedError 分支必须调 _mark_skipped,block:\n{block}"
    )
    assert "_mark_failed" not in block, (
        "AgentSkippedError 分支不得调 _mark_failed(会把 skipped 语义吞成 failed)"
    )
