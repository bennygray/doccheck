"""price_consistency Agent 共享子包 (C11 detect-agent-price-consistency)

C11 实现 4 子检测算法,共享:
- normalizer: item_name NFKC + Decimal 拆解
- extractor: 从 PriceItem 批量 query bidder 报价(按 sheet_name 分组)
- config: 子检测 flag + 阈值 + 权重 env 配置
- models: PriceRow / SubDimResult TypedDict 契约
- tail / amount_pattern / item_list / series_relation _detector: 4 子算法
- scorer: 4 子检测合成 Agent 级 score(disabled/skip 不参与归一化)

共享 helper `write_pair_comparison_row`:写 PairComparison 行(对齐 C10 metadata_impl)。
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
    """写一行 PairComparison。

    不写(session 为 None 或 bidder 缺失)时静默跳过 — L1 单元测试构造的
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
