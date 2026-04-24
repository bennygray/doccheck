"""L1 - engine._execute_agent_task 对 AgentSkippedError 的捕获顺序 (harden-async-infra D2)

核心约束:`except AgentSkippedError` MUST 出现在 `except Exception` **之前**,
否则通用 Exception 分支会吞掉 AgentSkippedError → 走 _mark_failed (status="failed")
而非 _mark_skipped (status="skipped")。

完整行为验证(AgentSkippedError → skipped / RuntimeError → failed)见 L2
`test_detect_subprocess_isolation.py`。此处 L1 做源码级 AST 校验,不需 DB。

**test-infra-followup-wave2 Item 2**:从正则 + 去注释 `_extract_code_lines` 升级为
AST `ast.AsyncFunctionDef` visitor(复用 `test_agent_except_skipped_guard.py` 的同型
pattern,内联不抽 shared helper 避参数爆炸)。消除字符串字面量里的 `#` 之类脆弱路径。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import app.services.detect.engine as engine_mod

_ENGINE_PATH = Path(engine_mod.__file__)
_TARGET_FUNC = "_execute_agent_task"


# ------------------------------------------------------------ AST helpers (内联)


def _handler_type_id(handler: ast.ExceptHandler) -> str | None:
    """返 except handler 的类型名(Name.id / Attribute.attr),裸 except 返 None。"""
    t = handler.type
    if t is None:
        return None
    if isinstance(t, ast.Name):
        return t.id
    if isinstance(t, ast.Attribute):
        return t.attr
    return None


def _is_broad_except(handler: ast.ExceptHandler) -> bool:
    """吞掉 AgentSkippedError 的通用 except: bare / Exception / BaseException。"""
    tid = _handler_type_id(handler)
    return tid is None or tid in ("Exception", "BaseException")


def _is_agent_skipped_except(handler: ast.ExceptHandler) -> bool:
    return _handler_type_id(handler) == "AgentSkippedError"


def _find_target_func(tree: ast.AST) -> ast.AsyncFunctionDef:
    """定位 engine._execute_agent_task(async def)。"""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == _TARGET_FUNC
        ):
            return node
    pytest.fail(f"engine.py 里找不到 async def {_TARGET_FUNC}")


def _parse_engine() -> ast.AsyncFunctionDef:
    src = _ENGINE_PATH.read_text(encoding="utf-8")
    return _find_target_func(ast.parse(src))


def _iter_try_nodes(func: ast.AsyncFunctionDef):
    for node in ast.walk(func):
        if isinstance(node, ast.Try):
            yield node


def _call_names_in_block(stmts: list[ast.stmt]) -> set[str]:
    """提取 block 内所有 Call 的名字(Name.id 或 Attribute.attr)。"""
    names: set[str] = set()
    for stmt in stmts:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Call):
                f = sub.func
                if isinstance(f, ast.Name):
                    names.add(f.id)
                elif isinstance(f, ast.Attribute):
                    names.add(f.attr)
    return names


# ------------------------------------------------------------ 测试 case


def test_engine_except_order_agent_skipped_before_broad_that_fails():
    """契约:`_execute_agent_task` 内,**body 调 `_mark_failed` 的 broad except**,
    其前必须有 `except AgentSkippedError` handler。

    理由:broad except 若 body 走 `_mark_failed` 路径,吞掉 AgentSkippedError 会让
    skipped 语义被错标为 failed(harden-async-infra H2 型隐患)。而 body 走
    `_mark_skipped` 的 broad except(如 preflight 错误处理)无此风险,不受本契约约束。
    """
    func = _parse_engine()
    violations: list[str] = []

    for try_node in _iter_try_nodes(func):
        for i, handler in enumerate(try_node.handlers):
            if not _is_broad_except(handler):
                continue
            body_calls = _call_names_in_block(handler.body)
            # 仅对"broad except → _mark_failed"强制 AgentSkippedError 前置
            if "_mark_failed" not in body_calls:
                continue
            has_skipped_before = any(
                _is_agent_skipped_except(h) for h in try_node.handlers[:i]
            )
            if not has_skipped_before:
                violations.append(
                    f"engine.py:{handler.lineno} {_TARGET_FUNC}: "
                    f"broad except at handler index {i} "
                    f"(type={_handler_type_id(handler)!r}) 调 _mark_failed 但前置"
                    f"未见 except AgentSkippedError;会吞 skipped 语义为 failed"
                )

    assert not violations, (
        "engine._execute_agent_task 的 except 顺序违规:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_engine_agent_skipped_branch_calls_mark_skipped():
    """AgentSkippedError 分支 body 必须调 `_mark_skipped`,不得调 `_mark_failed`。"""
    func = _parse_engine()
    checked_at_least_one = False

    for try_node in _iter_try_nodes(func):
        for handler in try_node.handlers:
            if not _is_agent_skipped_except(handler):
                continue
            checked_at_least_one = True
            calls = _call_names_in_block(handler.body)
            assert "_mark_skipped" in calls, (
                f"engine.py:{handler.lineno}: AgentSkippedError handler "
                f"body 未调 _mark_skipped。body calls: {sorted(calls)}"
            )
            assert "_mark_failed" not in calls, (
                f"engine.py:{handler.lineno}: AgentSkippedError handler "
                f"body 不得调 _mark_failed(会把 skipped 语义吞成 failed)"
            )

    assert checked_at_least_one, (
        "engine._execute_agent_task 未找到 `except AgentSkippedError` handler;"
        "harden-async-infra D2 契约失守"
    )


# ------------------------------------------------------------ 反向验证(Item 2 Task 2.3)
# 静态构造一个"顺序颠倒"的 AsyncFunctionDef,确认上面的核心断言函数会报错。
# 不修改真实 engine.py(避回归 + 避 race);直接 ast.parse 合成源码验证 visitor 敏感度。


_INVERTED_SRC = """
async def _execute_agent_task():
    try:
        await do()
    except Exception:
        _mark_failed()
    except AgentSkippedError:
        _mark_skipped()
"""


def test_visitor_catches_inverted_order_on_synthetic_source():
    """反向验证:手工构造 "except Exception(调 _mark_failed)在 AgentSkippedError 之前"
    的源码,核心契约函数应判定为违规。防 visitor 降级 / 逻辑倒挂。"""
    tree = ast.parse(_INVERTED_SRC)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == _TARGET_FUNC
    )

    violations: list[str] = []
    for try_node in _iter_try_nodes(func):
        for i, handler in enumerate(try_node.handlers):
            if not _is_broad_except(handler):
                continue
            body_calls = _call_names_in_block(handler.body)
            if "_mark_failed" not in body_calls:
                continue
            has_skipped_before = any(
                _is_agent_skipped_except(h) for h in try_node.handlers[:i]
            )
            if not has_skipped_before:
                violations.append(f"index {i} type={_handler_type_id(handler)}")

    assert violations, (
        "visitor 未捕获到 broad except(_mark_failed)先于 AgentSkippedError 的顺序违规;"
        "核心契约逻辑失效"
    )
    assert any("index 0" in v for v in violations)
