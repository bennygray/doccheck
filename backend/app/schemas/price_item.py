"""PriceItem Pydantic schemas (C5 parser-pipeline US-4.4)。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class PriceItemResponse(BaseModel):
    """``GET /api/projects/{pid}/bidders/{bid}/price-items`` 单条响应。"""

    id: int
    sheet_name: str
    row_index: int
    item_code: str | None
    item_name: str | None
    unit: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    total_price: Decimal | None
    created_at: datetime

    model_config = {"from_attributes": True}


__all__ = ["PriceItemResponse"]
