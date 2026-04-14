"""metadata Agent 共享子包 (C10 detect-agents-metadata)

3 个 metadata Agent(author/time/machine)共享:
- normalizer: NFKC+casefold+strip 归一化
- extractor: 从 DocumentMetadata 批量 query bidder 的元数据
- config: 子检测 flag + 权重等 env 配置
- models: TypedDict 契约
- author/time/machine_detector: 3 子算法
- scorer: 单维度合成 Agent 级 score

共享 helper `write_pair_comparison_row`:写 PairComparison 行给 engine 消费。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pair_comparison import PairComparison
from app.services.detect.context import AgentContext


async def write_pair_comparison_row(
    ctx: AgentContext,
    *,
    dimension: str,
    score: float,
    evidence: dict[str, Any],
    is_ironclad: bool = False,
) -> None:
    """写一行 PairComparison,共 3 metadata Agent 使用。

    不写(session 为 None 或 bidder 缺失)时静默跳过 — 单元测试构造的
    AgentContext 可能不带 session。
    """
    session: AsyncSession | None = ctx.session
    if session is None or ctx.bidder_a is None or ctx.bidder_b is None:
        return
    pc = PairComparison(
        project_id=ctx.project_id,
        version=ctx.version,
        bidder_a_id=ctx.bidder_a.id,
        bidder_b_id=ctx.bidder_b.id,
        dimension=dimension,
        score=Decimal(str(round(score, 2))),
        is_ironclad=is_ironclad,
        evidence_json=evidence,
    )
    session.add(pc)
    await session.flush()


__all__ = ["write_pair_comparison_row"]
