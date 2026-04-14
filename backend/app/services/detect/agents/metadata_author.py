"""metadata_author Agent 骨架 (pair 型) - C6 dummy,C10 真实实现。"""

from __future__ import annotations

from app.services.detect.agents._dummy import dummy_pair_run
from app.services.detect.agents._preflight_helpers import bidder_has_metadata
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.registry import register_agent


async def preflight(ctx: AgentContext) -> PreflightResult:
    if ctx.bidder_a is None or ctx.bidder_b is None or ctx.session is None:
        return PreflightResult("skip", "未提取到元数据")
    a_ok = await bidder_has_metadata(ctx.session, ctx.bidder_a.id, "author")
    b_ok = await bidder_has_metadata(ctx.session, ctx.bidder_b.id, "author")
    if a_ok and b_ok:
        return PreflightResult("ok")
    return PreflightResult("skip", "未提取到元数据")


@register_agent("metadata_author", "pair", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    return await dummy_pair_run(ctx, "metadata_author")
