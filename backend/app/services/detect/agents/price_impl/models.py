"""TypedDict 契约 (C11 price_impl)

仅内部类型契约,不做序列化;evidence_json 最终存 dict 到 JSONB。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, TypedDict


class PriceRow(TypedDict):
    """单条 PriceItem 快照 + 预计算字段(tail_key / item_name_norm / total_price_float)。"""

    price_item_id: int
    bidder_id: int
    sheet_name: str
    row_index: int
    item_name_raw: str | None
    item_name_norm: str | None
    unit_price_raw: Decimal | None
    total_price_raw: Decimal | None
    # 预计算字段
    total_price_float: float | None
    tail_key: tuple[str, int] | None  # (尾 N 位字符串, 整数位长)


class SubDimResult(TypedDict, total=False):
    """子检测返回结构(4 detector 共用)。

    score:0~1 hit_strength;None 表示子检测自身 skip(数据不足等);
    detector 不返 disabled 状态(由 scorer 根据 cfg 跳过)。
    """

    score: float | None
    reason: str | None
    hits: list[dict[str, Any]]


__all__ = ["PriceRow", "SubDimResult"]
