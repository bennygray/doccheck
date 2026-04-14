"""C6 dummy run 共享辅助 (C7~C13 接入真实 Agent 时可删除或改写)

- `dummy_pair_run`:pair 型 Agent 的 dummy run,写 PairComparison 行
- `dummy_global_run`:global 型 Agent 的 dummy run,写 OverallAnalysis 行

dummy 行为:sleep 0.2~1.0s + 随机 0~100 分 + 10% 概率 is_ironclad=true(pair 型才有)。
"""

from __future__ import annotations

import asyncio
import random
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.services.detect.context import AgentContext, AgentRunResult


async def dummy_pair_run(
    ctx: AgentContext, dimension: str
) -> AgentRunResult:
    """pair 型 dummy run:写一行 PairComparison + 返 score/summary。"""
    if ctx.bidder_a is None or ctx.bidder_b is None:
        # 理论上 pair 型 preflight 保证双方非空;防御性检查
        return AgentRunResult(score=0.0, summary=f"dummy {dimension} skipped: no pair")

    await asyncio.sleep(random.uniform(0.2, 1.0))
    score = round(random.uniform(0.0, 100.0), 2)
    is_ironclad = random.random() < 0.10  # 10% 铁证
    summary = f"dummy {dimension} result ({ctx.bidder_a.name} vs {ctx.bidder_b.name})"

    session: AsyncSession | None = ctx.session
    if session is not None:
        pc = PairComparison(
            project_id=ctx.project_id,
            version=ctx.version,
            bidder_a_id=ctx.bidder_a.id,
            bidder_b_id=ctx.bidder_b.id,
            dimension=dimension,
            score=Decimal(str(score)),
            is_ironclad=is_ironclad,
            evidence_json={"dummy": True},
        )
        session.add(pc)
        await session.flush()

    return AgentRunResult(score=score, summary=summary, evidence_json={"dummy": True})


async def dummy_global_run(
    ctx: AgentContext, dimension: str
) -> AgentRunResult:
    """global 型 dummy run:写一行 OverallAnalysis + 返 score/summary。"""
    await asyncio.sleep(random.uniform(0.2, 1.0))
    score = round(random.uniform(0.0, 100.0), 2)
    note = " (降级)" if ctx.downgrade else ""
    summary = f"dummy {dimension} result{note}"

    session: AsyncSession | None = ctx.session
    if session is not None:
        oa = OverallAnalysis(
            project_id=ctx.project_id,
            version=ctx.version,
            dimension=dimension,
            score=Decimal(str(score)),
            evidence_json={"dummy": True, "downgrade": ctx.downgrade},
        )
        session.add(oa)
        await session.flush()

    return AgentRunResult(
        score=score,
        summary=summary,
        evidence_json={"dummy": True, "downgrade": ctx.downgrade},
    )


__all__ = ["dummy_pair_run", "dummy_global_run"]
