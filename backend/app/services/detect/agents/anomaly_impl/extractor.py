"""C12 bidder 报价聚合 (anomaly_impl)

aggregate_bidder_totals:
- 单次 SQL:JOIN bidders × price_items,GROUP BY bidder,SUM(total_price)
- 过滤 bidders.deleted_at IS NULL + project_id
- 只返"有 price_items 的 bidder"(无 price_item 的 bidder 自动被 INNER JOIN 过滤)
- 按 bidder_id 升序(测试可重现)
- max_bidders 截断
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bidder import Bidder
from app.models.price_item import PriceItem
from app.services.detect.agents.anomaly_impl.config import AnomalyConfig
from app.services.detect.agents.anomaly_impl.models import BidderPriceSummary

logger = logging.getLogger(__name__)


async def aggregate_bidder_totals(
    session: AsyncSession,
    project_id: int,
    cfg: AnomalyConfig,
) -> list[BidderPriceSummary]:
    """聚合项目下所有 bidder 的总报价。

    - SUM(price_items.total_price) per bidder
    - NULL total_price 自动被 SUM 忽略(SQL 语义)
    - 若 bidder 所有 total_price 均 NULL → SUM 返 NULL → float(None) 会抛异常
      → 这种 bidder 本身没有有效报价,直接过滤掉
    - 按 bidder_id 升序,截断 max_bidders
    """
    stmt = (
        select(
            Bidder.id,
            Bidder.name,
            func.sum(PriceItem.total_price).label("total"),
        )
        .select_from(Bidder)
        .join(PriceItem, PriceItem.bidder_id == Bidder.id)
        .where(
            Bidder.project_id == project_id,
            Bidder.deleted_at.is_(None),
        )
        .group_by(Bidder.id, Bidder.name)
        .order_by(Bidder.id.asc())
        .limit(cfg.max_bidders)
    )
    rows = (await session.execute(stmt)).all()
    summaries: list[BidderPriceSummary] = []
    for bidder_id, bidder_name, total in rows:
        # total 为 NULL 或 0 表示所有 price_items 总价都无效,过滤掉
        if total is None:
            continue
        try:
            total_float = float(total) if isinstance(total, Decimal) else float(total)
        except (TypeError, ValueError):
            logger.warning(
                "bidder %s total_price conversion failed, skipping",
                bidder_id,
            )
            continue
        summaries.append(
            BidderPriceSummary(
                bidder_id=bidder_id,
                bidder_name=bidder_name,
                total_price=total_float,
            )
        )
    return summaries


__all__ = ["aggregate_bidder_totals"]
