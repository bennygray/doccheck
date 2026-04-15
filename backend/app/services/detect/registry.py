"""Agent 注册表 (C6 detect-framework D2 + C12 扩展至 11)

11 Agent 通过 @register_agent 装饰器注册到模块级 AGENT_REGISTRY dict。
C7~C13 各 change 替换对应 run() 实现,不改 preflight / 注册 key。
C12 新增 global 型 `price_anomaly`(11 = pair 7 + global 4)。
"""

from __future__ import annotations

from typing import Awaitable, Callable, Literal, NamedTuple

from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)

PreflightFn = Callable[[AgentContext], Awaitable[PreflightResult]]
RunFn = Callable[[AgentContext], Awaitable[AgentRunResult]]

# C12 扩至 11;与 `len(AGENT_REGISTRY)` 一致性由 L1 test 断言
EXPECTED_AGENT_COUNT: int = 11


class AgentSpec(NamedTuple):
    name: str
    agent_type: Literal["pair", "global"]
    preflight: PreflightFn
    run: RunFn


AGENT_REGISTRY: dict[str, AgentSpec] = {}


def register_agent(
    name: str,
    agent_type: Literal["pair", "global"],
    preflight: PreflightFn,
) -> Callable[[RunFn], RunFn]:
    """装饰 Agent 的 run() 函数,写入 AGENT_REGISTRY。

    重复注册同名抛 ValueError(模块加载期就会暴露,避免静默覆盖)。
    """

    def decorator(run_fn: RunFn) -> RunFn:
        if name in AGENT_REGISTRY:
            raise ValueError(f"agent already registered: {name}")
        AGENT_REGISTRY[name] = AgentSpec(
            name=name,
            agent_type=agent_type,
            preflight=preflight,
            run=run_fn,
        )
        return run_fn

    return decorator


def get_agent(name: str) -> AgentSpec | None:
    """按 name 查 AGENT_REGISTRY(标准 dict.get 语义,缺失返 None)。"""
    return AGENT_REGISTRY.get(name)


def get_all_agents() -> list[AgentSpec]:
    """返回当前注册的所有 AgentSpec。"""
    return list(AGENT_REGISTRY.values())


__all__ = [
    "AGENT_REGISTRY",
    "EXPECTED_AGENT_COUNT",
    "AgentSpec",
    "PreflightFn",
    "RunFn",
    "get_agent",
    "get_all_agents",
    "register_agent",
]
