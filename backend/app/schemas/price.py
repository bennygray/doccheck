"""价格相关 Pydantic schemas (C4 file-upload §6.3)。

对应 spec.md "项目报价元配置" + "报价列映射规则骨架" 两个 Requirement。
枚举值 + JSONB column_mapping 必需键的校验在此层做(避免重复散在路由)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

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
    """``PUT /api/projects/{pid}/price-rules`` 入参(单条)。

    parser-accuracy-fixes P1-5:
    - 新 payload:传 `sheets_config: [...]`(权威)
    - 老 payload(向后兼容):传 `column_mapping + sheet_name + header_row` → 自动包装单 sheet
    - 混传(两者同时):返 422(M4)
    """

    # 新字段(P1-5 权威)
    sheets_config: list[dict[str, Any]] | None = None
    # 老字段(deprecated,向后兼容;作老 admin UI 单 sheet PUT 入口)
    sheet_name: str | None = Field(default=None, min_length=1, max_length=200)
    header_row: int | None = Field(default=None, ge=1)
    column_mapping: dict[str, Any] | None = None
    created_by_llm: bool = False
    confirmed: bool = False
    # 更新已有规则时传 id;无 id 视为新增
    id: int | None = None

    @model_validator(mode="after")
    def _validate_payload_shape(self) -> "PriceParsingRuleWrite":
        has_new = self.sheets_config is not None
        has_old = any(
            v is not None for v in (self.sheet_name, self.header_row, self.column_mapping)
        )
        # M4:混传返 422
        if has_new and has_old:
            raise ValueError(
                "sheets_config 与 column_mapping/sheet_name/header_row 只能二选一"
            )
        if not has_new and not has_old:
            raise ValueError(
                "必须至少传 sheets_config 或 (sheet_name + header_row + column_mapping)"
            )
        # 校验新 payload 每项必需键
        if has_new:
            if not self.sheets_config:
                raise ValueError("sheets_config 不能为空数组")
            for i, item in enumerate(self.sheets_config):
                if not isinstance(item, dict):
                    raise ValueError(f"sheets_config[{i}] 必须是对象")
                sn = item.get("sheet_name")
                hr = item.get("header_row")
                cm = item.get("column_mapping")
                if not isinstance(sn, str) or not sn:
                    raise ValueError(f"sheets_config[{i}].sheet_name 非法")
                if not isinstance(hr, int) or hr < 1:
                    raise ValueError(f"sheets_config[{i}].header_row 非法")
                if not isinstance(cm, dict):
                    raise ValueError(f"sheets_config[{i}].column_mapping 非法")
                missing = REQUIRED_MAPPING_KEYS - set(cm.keys())
                if missing:
                    raise ValueError(
                        f"sheets_config[{i}].column_mapping 缺少必需键: {sorted(missing)}"
                    )
                # fix-multi-sheet-price-double-count B:sheet_role 校验(可选字段,缺则后端默认 main)
                role = item.get("sheet_role")
                if role is not None and role not in ("main", "breakdown", "summary"):
                    raise ValueError(
                        f"sheets_config[{i}].sheet_role 非法,必须 main/breakdown/summary"
                    )
        # 校验老 payload 三字段齐全 + column_mapping 必需键
        if has_old:
            if not self.sheet_name or self.header_row is None or self.column_mapping is None:
                raise ValueError("老 payload 必须同时传 sheet_name + header_row + column_mapping")
            missing = REQUIRED_MAPPING_KEYS - set(self.column_mapping.keys())
            if missing:
                raise ValueError(f"column_mapping 缺少必需键: {sorted(missing)}")
        return self

    def normalized_sheets_config(self) -> list[dict[str, Any]]:
        """统一输出 sheets_config 数组(老 payload 包装成单 sheet)。

        fix-multi-sheet-price-double-count:每项 sheet_role 缺则默认 'main'(backward compat)。
        """
        if self.sheets_config is not None:
            # 副本 + 默认 sheet_role='main'(若缺)
            normalized: list[dict[str, Any]] = []
            for item in self.sheets_config:
                copied = dict(item)
                copied.setdefault("sheet_role", "main")
                normalized.append(copied)
            return normalized
        return [
            {
                "sheet_name": self.sheet_name,
                "sheet_role": "main",
                "header_row": self.header_row,
                "column_mapping": self.column_mapping,
            }
        ]


class PriceParsingRuleRead(BaseModel):
    """``GET /price-rules`` 单条响应。"""

    id: int
    project_id: int
    # 新字段(权威)
    sheets_config: list[dict[str, Any]] = Field(default_factory=list)
    # 老字段(deprecated,但仍暴露做 backward compat;老 admin UI GET 仍读这 3 个)
    sheet_name: str | None = None
    header_row: int | None = None
    column_mapping: dict[str, Any] | None = None
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
