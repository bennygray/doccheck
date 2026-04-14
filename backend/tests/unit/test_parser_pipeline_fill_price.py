"""L1 - parser/pipeline/fill_price 单元测试 (C5 §9.7)

覆盖归一化(千分位/数值/空行)与 terminal 判定分支。
大部分纯 Python 逻辑,不走 DB。
"""

from __future__ import annotations

from decimal import Decimal

from app.services.parser.pipeline.fill_price import (
    _letter_to_idx,
    _parse_decimal,
)


def test_letter_to_idx() -> None:
    assert _letter_to_idx("A") == 0
    assert _letter_to_idx("B") == 1
    assert _letter_to_idx("Z") == 25
    assert _letter_to_idx("AA") == 26
    assert _letter_to_idx("") is None
    assert _letter_to_idx("1") is None


def test_parse_decimal_int() -> None:
    assert _parse_decimal(100, scale=2) == Decimal("100")


def test_parse_decimal_float() -> None:
    assert _parse_decimal(100.5, scale=2) == Decimal("100.5")


def test_parse_decimal_thousand_sep() -> None:
    assert _parse_decimal("1,234.56", scale=2) == Decimal("1234.56")


def test_parse_decimal_currency() -> None:
    assert _parse_decimal("￥1,234.50", scale=2) == Decimal("1234.5")


def test_parse_decimal_chinese_uppercase_returns_none() -> None:
    # 中文大写归一化未实现 → 返 None(不阻断,字段 NULL)
    assert _parse_decimal("壹万元整", scale=2) is None


def test_parse_decimal_empty() -> None:
    assert _parse_decimal("", scale=2) is None
    assert _parse_decimal("   ", scale=2) is None
    assert _parse_decimal(None, scale=2) is None


def test_parse_decimal_non_number() -> None:
    assert _parse_decimal("abc", scale=2) is None


def test_parse_decimal_negative() -> None:
    assert _parse_decimal("-100.5", scale=2) == Decimal("-100.5")
