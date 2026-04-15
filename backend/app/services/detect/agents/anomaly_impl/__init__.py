"""price_anomaly Agent 共享子包 (C12 detect-agent-price-anomaly)

C12 实现单家异常低价检测(垂直关系:单家 vs 群体均值),共享:
- config: 7 env (PRICE_ANOMALY_*) + AnomalyConfig dataclass
- models: BidderPriceSummary / AnomalyOutlier / DetectionResult TypedDict
- extractor: 聚合 bidder 总价(单次 SQL,按 bidder_id 升序 + max_bidders 截断)
- detector: 均值偏离判定(本期仅 direction='low')
- scorer: Agent 级 score 合成(占位公式)

共享 helper `write_overall_analysis_row`:写 OverallAnalysis 行(对齐 C11 price_impl
的 `write_pair_comparison_row` 风格;global 型 Agent 使用)。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.overall_analysis import OverallAnalysis
from app.services.detect.context import AgentContext


async def write_overall_analysis_row(
    ctx: AgentContext,
    *,
    dimension: str,
    score: float,
    evidence: dict[str, Any],
) -> None:
    """写一行 OverallAnalysis。

    不写(session 为 None)时静默跳过 — L1 单元测试构造的 AgentContext
    可能不带 session。
    """
    session: AsyncSession | None = ctx.session
    if session is None:
        return
    oa = OverallAnalysis(
        project_id=ctx.project_id,
        version=ctx.version,
        dimension=dimension,
        score=Decimal(str(round(score, 2))),
        evidence_json=evidence,
    )
    session.add(oa)
    await session.flush()


__all__ = ["write_overall_analysis_row"]
