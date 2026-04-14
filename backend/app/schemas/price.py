"""价格相关 Pydantic schemas (C4 file-upload §6.3)。

对应 spec.md "项目报价元配置" + "报价列映射规则骨架" 两个 Requirement。
枚举值 + JSONB column_mapping 必需键的校验在此层做(避免重复散在路由)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.price_config import CURRENCIES, UNIT_SCALES
from app.models.price_parsing_rule import REQUIRED_MAPPING_KEYS


class ProjectPriceConfigWrite(BaseModel):
    """``PUT /api/projects/{pid}/price-config`` 入参。"""

    currency: str
    tax_inclusive: bool
    unit_scale: str

    @field_validator("currency")
    @classmethod
    def _check_currency(cls, v: str) -> str:
        if v not in CURRENCIES:
            raise ValueError(f"currency 必须为 {sorted(CURRENCIES)} 之一")
        return v

    @field_validator("unit_scale")
    @classmethod
    def _check_unit_scale(cls, v: str) -> str:
        if v not in UNIT_SCALES:
            raise ValueError(f"unit_scale 必须为 {sorted(UNIT_SCALES)} 之一")
        return v


class ProjectPriceConfigRead(ProjectPriceConfigWrite):
    """``GET /price-config`` 返回。"""

    project_id: int
    updated_at: datetime

    model_config = {"from_attributes": True}


class PriceParsingRuleWrite(BaseModel):
    """``PUT /api/projects/{pid}/price-rules`` 入参(单条)。"""

    sheet_name: str = Field(..., min_length=1, max_length=200)
    header_row: int = Field(..., ge=1)
    column_mapping: dict[str, Any]
    created_by_llm: bool = False
    confirmed: bool = False
    # 更新已有规则时传 id;无 id 视为新增
    id: int | None = None

    @field_validator("column_mapping")
    @classmethod
    def _validate_mapping(cls, v: dict[str, Any]) -> dict[str, Any]:
        missing = REQUIRED_MAPPING_KEYS - set(v.keys())
        if missing:
            raise ValueError(f"column_mapping 缺少必需键: {sorted(missing)}")
        return v


class PriceParsingRuleRead(BaseModel):
    """``GET /price-rules`` 单条响应。"""

    id: int
    project_id: int
    sheet_name: str
    header_row: int
    column_mapping: dict[str, Any]
    created_by_llm: bool
    confirmed: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


__all__ = [
    "PriceParsingRuleRead",
    "PriceParsingRuleWrite",
    "ProjectPriceConfigRead",
    "ProjectPriceConfigWrite",
]
