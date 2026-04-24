"""L1:PUT /api/projects/{pid}/price-rules 新/老 payload 兼容(parser-accuracy-fixes P1-5)

只测 Pydantic 校验层(PriceParsingRuleWrite);路由层 integration 走 L2。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.price import PriceParsingRuleWrite


_VALID_MAPPING = {
    "code_col": "A",
    "name_col": "B",
    "unit_col": "C",
    "qty_col": "D",
    "unit_price_col": "E",
    "total_price_col": "F",
    "skip_cols": [],
}


class TestNewPayload:
    """新 payload:sheets_config"""

    def test_single_sheet_accepted(self):
        body = PriceParsingRuleWrite.model_validate(
            {
                "sheets_config": [
                    {"sheet_name": "报价表", "header_row": 2, "column_mapping": _VALID_MAPPING}
                ]
            }
        )
        normalized = body.normalized_sheets_config()
        assert len(normalized) == 1
        assert normalized[0]["sheet_name"] == "报价表"

    def test_multi_sheet_accepted(self):
        body = PriceParsingRuleWrite.model_validate(
            {
                "sheets_config": [
                    {"sheet_name": "报价表", "header_row": 2, "column_mapping": _VALID_MAPPING},
                    {"sheet_name": "分析表", "header_row": 1, "column_mapping": _VALID_MAPPING},
                ]
            }
        )
        assert len(body.normalized_sheets_config()) == 2

    def test_empty_sheets_config_rejected(self):
        with pytest.raises(ValidationError):
            PriceParsingRuleWrite.model_validate({"sheets_config": []})

    def test_missing_required_key_in_mapping_rejected(self):
        bad_mapping = {k: v for k, v in _VALID_MAPPING.items() if k != "code_col"}
        with pytest.raises(ValidationError):
            PriceParsingRuleWrite.model_validate(
                {
                    "sheets_config": [
                        {"sheet_name": "s", "header_row": 1, "column_mapping": bad_mapping}
                    ]
                }
            )

    def test_header_row_invalid_rejected(self):
        with pytest.raises(ValidationError):
            PriceParsingRuleWrite.model_validate(
                {
                    "sheets_config": [
                        {"sheet_name": "s", "header_row": 0, "column_mapping": _VALID_MAPPING}
                    ]
                }
            )


class TestLegacyPayload:
    """老 payload:column_mapping + sheet_name + header_row(backward compat)"""

    def test_legacy_accepted_and_normalized(self):
        body = PriceParsingRuleWrite.model_validate(
            {
                "sheet_name": "报价清单",
                "header_row": 3,
                "column_mapping": _VALID_MAPPING,
            }
        )
        normalized = body.normalized_sheets_config()
        assert len(normalized) == 1
        assert normalized[0]["sheet_name"] == "报价清单"
        assert normalized[0]["header_row"] == 3

    def test_legacy_missing_required_key(self):
        with pytest.raises(ValidationError):
            PriceParsingRuleWrite.model_validate(
                {
                    "sheet_name": "s",
                    "header_row": 1,
                    "column_mapping": {k: v for k, v in _VALID_MAPPING.items() if k != "code_col"},
                }
            )

    def test_legacy_incomplete_fields(self):
        """老 payload 3 字段必须齐全"""
        with pytest.raises(ValidationError):
            PriceParsingRuleWrite.model_validate(
                {"sheet_name": "s", "column_mapping": _VALID_MAPPING}  # 缺 header_row
            )


class TestMixedPayload:
    """M4:混传(老+新同时)返 422"""

    def test_both_sheets_config_and_column_mapping_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            PriceParsingRuleWrite.model_validate(
                {
                    "sheets_config": [
                        {"sheet_name": "s", "header_row": 1, "column_mapping": _VALID_MAPPING}
                    ],
                    "column_mapping": _VALID_MAPPING,
                }
            )
        # 报错信息明确提示二选一
        assert "二选一" in str(exc_info.value)

    def test_both_sheets_config_and_sheet_name_rejected(self):
        """即使 column_mapping 没传,sheet_name 也算老字段"""
        with pytest.raises(ValidationError):
            PriceParsingRuleWrite.model_validate(
                {
                    "sheets_config": [
                        {"sheet_name": "s", "header_row": 1, "column_mapping": _VALID_MAPPING}
                    ],
                    "sheet_name": "another",
                }
            )


class TestEmptyPayload:
    def test_no_fields_rejected(self):
        with pytest.raises(ValidationError):
            PriceParsingRuleWrite.model_validate({})
