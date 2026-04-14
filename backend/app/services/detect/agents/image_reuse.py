"""image_reuse Agent 骨架 (global 型) - C6 dummy,真实实现留后续。

preflight:≥2 bidder 有 document_images → ok。
"""

from __future__ import annotations

from app.services.detect.agents._dummy import dummy_global_run
from app.services.detect.agents._preflight_helpers import bidder_has_images
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.registry import register_agent


async def preflight(ctx: AgentContext) -> PreflightResult:
    if len(ctx.all_bidders) < 2 or ctx.session is None:
        return PreflightResult("skip", "未提取到图片")
    count = 0
    for b in ctx.all_bidders:
        if await bidder_has_images(ctx.session, b.id):
            count += 1
            if count >= 2:
                return PreflightResult("ok")
    return PreflightResult("skip", "未提取到图片")


@register_agent("image_reuse", "global", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    return await dummy_global_run(ctx, "image_reuse")
