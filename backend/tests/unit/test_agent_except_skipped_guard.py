"""L1 - agent 层 try/except 顺序元测试 (agent-skipped-error-guard)

核心约束:所有 `backend/app/services/detect/agents/*.py` 顶层文件里的 `async def
run()` 函数,若内部有 `except Exception` / `except BaseException` / 裸 except,
则**必须**在其之前有一个 `except AgentSkippedError` handler,否则 agent 未来抛
AgentSkippedError 时会被通用 except 吞掉变 failed → 绕过 skipped 语义。

防回归 harden-async-infra H2 同型隐患。

用 AST 而非正则(reviewer L1 警示注释/docstring 里 `except` 字面量会误伤)。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# agents 顶层目录,不递归 _impl 子包(helper 异常逸出到 agent 入口即被约束)
_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "app" / "services" / "detect" / "agents"


def _list_agent_files() -> list[Path]:
    """列出 agents 顶层 *.py,跳过 __init__ 和 _ 前缀 helper。"""
    return [
        p
        for p in _AGENTS_DIR.glob("*.py")
        if not p.name.startswith("_") and p.name != "__init__.py"
    ]


def _find_run_funcs(tree: ast.AST) -> list[ast.AsyncFunctionDef]:
    """找出顶层 `async def run(...)` 函数(agent 约定入口名)。"""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run"
    ]


def _is_broad_except(handler: ast.ExceptHandler) -> bool:
    """判断是否是会吞 AgentSkippedError 的通用 except。

    触发场景:
    - `except:`(handler.type is None)
    - `except Exception [as e]:`(handler.type.id == "Exception")
    - `except BaseException [as e]:`(handler.type.id == "BaseException")
    """
    if handler.type is None:
        return True  # 裸 except
    if isinstance(handler.type, ast.Name):
        return handler.type.id in ("Exception", "BaseException")
    return False


def _is_agent_skipped_except(handler: ast.ExceptHandler) -> bool:
    """判断是否是 `except AgentSkippedError [as e]:` handler。"""
    if handler.type is None:
        return False
    # 支持 Name (直接 import) 和 Attribute (errors.AgentSkippedError) 两种写法
    if isinstance(handler.type, ast.Name):
        return handler.type.id == "AgentSkippedError"
    if isinstance(handler.type, ast.Attribute):
        return handler.type.attr == "AgentSkippedError"
    # tuple:except (AgentSkippedError, X):也算覆盖
    if isinstance(handler.type, ast.Tuple):
        return any(
            (isinstance(el, ast.Name) and el.id == "AgentSkippedError")
            or (isinstance(el, ast.Attribute) and el.attr == "AgentSkippedError")
            for el in handler.type.elts
        )
    return False


def _check_try_handlers_order(
    try_node: ast.Try, file_path: Path, func_name: str
) -> list[str]:
    """对单个 ast.Try 节点检查 handlers 顺序;返 error 消息列表(空 = 合规)。"""
    errors: list[str] = []
    for i, handler in enumerate(try_node.handlers):
        if _is_broad_except(handler):
            # 要求其前至少有一个 AgentSkippedError handler
            has_skipped_before = any(
                _is_agent_skipped_except(h) for h in try_node.handlers[:i]
            )
            if not has_skipped_before:
                errors.append(
                    f"{file_path.name}::{func_name} (line {handler.lineno}): "
                    f"found broad `except {_handler_type_repr(handler)}` without "
                    f"preceding `except AgentSkippedError: raise` guard. "
                    f"Broad except will silently swallow AgentSkippedError → "
                    f"status=failed instead of skipped(harden-async-infra H2 同型隐患)。"
                )
    return errors


def _handler_type_repr(handler: ast.ExceptHandler) -> str:
    if handler.type is None:
        return ""  # 裸 except
    if isinstance(handler.type, ast.Name):
        return handler.type.id
    return ast.unparse(handler.type)


@pytest.mark.parametrize("agent_file", _list_agent_files(), ids=lambda p: p.name)
def test_agent_run_func_has_agent_skipped_error_guard(agent_file: Path) -> None:
    """逐 agent 文件检查:每个 `async def run()` 内的 try 若有 broad except,
    前面必须有 except AgentSkippedError handler。"""
    try:
        tree = ast.parse(agent_file.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        pytest.fail(f"AST parse failed for {agent_file}: {exc}")

    run_funcs = _find_run_funcs(tree)
    if not run_funcs:
        pytest.skip(f"no `async def run()` in {agent_file.name}")

    all_errors: list[str] = []
    for func in run_funcs:
        for node in ast.walk(func):
            if isinstance(node, ast.Try):
                all_errors.extend(
                    _check_try_handlers_order(node, agent_file, func.name)
                )

    assert not all_errors, "\n" + "\n".join(all_errors)


def test_meta_test_finds_agents() -> None:
    """sanity:扫出来至少 6 个 agent 文件(pair + global 合计 11 期待值)。"""
    files = _list_agent_files()
    assert len(files) >= 6, (
        f"expected >=6 agent files under {_AGENTS_DIR}, found {len(files)}"
    )
