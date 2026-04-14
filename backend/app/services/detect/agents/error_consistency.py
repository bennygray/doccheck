"""error_consistency Agent 骨架 (global 型,带 downgrade) - C6 dummy。

US-5.2 特殊语义:identity_info 为空 → **降级运行**(不 skip),
退化为用 bidder.name 做纯关键词交叉搜索。真实降级逻辑留 C7~C13。
"""

from __future__ import annotations

from app.services.detect.agents._dummy import dummy_global_run
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.registry import register_agent


async def preflight(ctx: AgentContext) -> PreflightResult:
    """≥2 bidder 才有意义;任一 bidder 缺 identity_info → downgrade。"""
    if len(ctx.all_bidders) < 2:
        return PreflightResult("skip", "有效投标人不足")
    # 任一 bidder identity_info 为空 → 降级(不 skip)
    any_missing = any(
        not b.identity_info for b in ctx.all_bidders
    )
    if any_missing:
        return PreflightResult(
            "downgrade",
            "降级检测,建议补充标识信息后重新检测",
        )
    return PreflightResult("ok")


@register_agent("error_consistency", "global", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    return await dummy_global_run(ctx, "error_consistency")
