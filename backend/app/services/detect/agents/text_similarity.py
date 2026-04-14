"""text_similarity Agent 骨架 (pair 型) - C6 dummy,C7 真实实现。"""

from __future__ import annotations

from app.services.detect.agents._dummy import dummy_pair_run
from app.services.detect.agents._preflight_helpers import bidders_share_any_role
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.registry import register_agent


async def preflight(ctx: AgentContext) -> PreflightResult:
    if ctx.bidder_a is None or ctx.bidder_b is None or ctx.session is None:
        return PreflightResult("skip", "缺少可对比文档")
    if await bidders_share_any_role(
        ctx.session, ctx.bidder_a.id, ctx.bidder_b.id
    ):
        return PreflightResult("ok")
    return PreflightResult("skip", "缺少可对比文档")


@register_agent("text_similarity", "pair", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    return await dummy_pair_run(ctx, "text_similarity")
