"""从 PriceItem 批量 query bidder 报价 (C11 price_impl)

按 sheet_name 分组返回,每条行内预计算 tail_key / item_name_norm / total_price_float。
4 子检测共消费这一份数据,避免重复 query。
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price_item import PriceItem
from app.services.detect.agents.price_impl.config import PriceConfig
from app.services.detect.agents.price_impl.models import PriceRow
from app.services.detect.agents.price_impl.normalizer import (
    decimal_to_float_safe,
    normalize_item_name,
    split_price_tail,
)


async def extract_bidder_prices(
    session: AsyncSession, bidder_id: int, cfg: PriceConfig
) -> dict[str, list[PriceRow]]:
    """返回 bidder 名下 PriceItem 按 sheet_name 分组的列表(每行预计算关键字段)。

    cfg.max_rows_per_bidder 限流(超出截断防止极端文档拉爆内存)。
    顺序:按 (sheet_name, row_index)。
    """
    stmt = (
        select(PriceItem)
        .where(PriceItem.bidder_id == bidder_id)
        .order_by(PriceItem.sheet_name, PriceItem.row_index)
        .limit(cfg.max_rows_per_bidder)
    )
    items = (await session.execute(stmt)).scalars().all()
    grouped: dict[str, list[PriceRow]] = defaultdict(list)
    tail_n = cfg.tail.tail_n
    for it in items:
        grouped[it.sheet_name].append(
            {
                "price_item_id": it.id,
                "bidder_id": bidder_id,
                "sheet_name": it.sheet_name,
                "row_index": it.row_index,
                "item_name_raw": it.item_name,
                "item_name_norm": normalize_item_name(it.item_name),
                "unit_price_raw": it.unit_price,
                "total_price_raw": it.total_price,
                "total_price_float": decimal_to_float_safe(it.total_price),
                "tail_key": split_price_tail(it.total_price, tail_n),
                # detect-tender-baseline §5:加载 BOQ baseline hash(parser fill_price 写入,
                # 老数据 / 不完整行为 NULL,detector filter 时跳过 NULL 不假阳)
                "boq_baseline_hash": it.boq_baseline_hash,
            }
        )
    return dict(grouped)


def flatten_rows(grouped: dict[str, list[PriceRow]]) -> list[PriceRow]:
    """把按 sheet_name 分组的 dict flatten 成单 list(tail / amount_pattern 用)。"""
    return [r for rows in grouped.values() for r in rows]


__all__ = ["extract_bidder_prices", "flatten_rows"]
