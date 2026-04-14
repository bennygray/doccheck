"""style Agent 骨架 (global 型) - C6 dummy。

preflight:≥2 bidder 有同角色文档 → ok;否则 skip。
≥20 bidder 自动分组的策略(US-5.2)留 C13 真实实现时再落地,C6 dummy 不做。
"""

from __future__ import annotations

from app.services.detect.agents._dummy import dummy_global_run
from app.services.detect.agents._preflight_helpers import bidder_has_role
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.registry import register_agent


async def preflight(ctx: AgentContext) -> PreflightResult:
    if len(ctx.all_bidders) < 2 or ctx.session is None:
        return PreflightResult("skip", "缺少可对比文档")
    count_with_role = 0
    for b in ctx.all_bidders:
        if await bidder_has_role(ctx.session, b.id, None):
            count_with_role += 1
            if count_with_role >= 2:
                return PreflightResult("ok")
    return PreflightResult("skip", "缺少可对比文档")


@register_agent("style", "global", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    return await dummy_global_run(ctx, "style")
