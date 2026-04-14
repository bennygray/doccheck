"""L1 单元 - price schemas 枚举 + JSONB 必需键 (C4 §10.5)。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.price import PriceParsingRuleWrite, ProjectPriceConfigWrite


# ----------------------------------------------- ProjectPriceConfigWrite

class TestPriceConfig:
    def test_legal_cny(self) -> None:
        cfg = ProjectPriceConfigWrite(
            currency="CNY", tax_inclusive=True, unit_scale="yuan"
        )
        assert cfg.currency == "CNY"

    def test_illegal_currency(self) -> None:
        with pytest.raises(ValidationError, match="currency"):
            ProjectPriceConfigWrite(
                currency="JPY", tax_inclusive=True, unit_scale="yuan"
            )

    def test_illegal_unit_scale(self) -> None:
        with pytest.raises(ValidationError, match="unit_scale"):
            ProjectPriceConfigWrite(
                currency="CNY", tax_inclusive=True, unit_scale="kilo"
            )


# ----------------------------------------------- PriceParsingRuleWrite

_VALID_MAPPING = {
    "code_col": "A",
    "name_col": "B",
    "unit_col": "C",
    "qty_col": "D",
    "unit_price_col": "E",
    "total_price_col": "F",
}


class TestPriceRule:
    def test_legal_mapping(self) -> None:
        rule = PriceParsingRuleWrite(
            sheet_name="报价清单",
            header_row=2,
            column_mapping=_VALID_MAPPING,
        )
        assert rule.sheet_name == "报价清单"

    def test_missing_required_key(self) -> None:
        bad = {k: v for k, v in _VALID_MAPPING.items() if k != "code_col"}
        with pytest.raises(ValidationError, match="code_col"):
            PriceParsingRuleWrite(
                sheet_name="x", header_row=1, column_mapping=bad
            )

    def test_extra_keys_allowed(self) -> None:
        # 多余键(skip_cols / 业务自定义)允许通过;只校验"必需键齐全"
        mapping = {**_VALID_MAPPING, "skip_cols": ["G", "H"], "memo_col": "I"}
        rule = PriceParsingRuleWrite(
            sheet_name="x", header_row=1, column_mapping=mapping
        )
        assert rule.column_mapping["skip_cols"] == ["G", "H"]

    def test_header_row_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            PriceParsingRuleWrite(
                sheet_name="x", header_row=0, column_mapping=_VALID_MAPPING
            )

    def test_sheet_name_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PriceParsingRuleWrite(
                sheet_name="", header_row=1, column_mapping=_VALID_MAPPING
            )
