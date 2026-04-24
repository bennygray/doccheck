"""L1:_parse_decimal 扩"元/万元/万"后缀(parser-accuracy-fixes P0-3)

覆盖扩展矩阵 + 既有行为回归。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.parser.pipeline.fill_price import _parse_decimal


class TestNumericTypes:
    def test_int_passthrough(self):
        assert _parse_decimal(486000, scale=2) == Decimal("486000")

    def test_float_passthrough(self):
        assert _parse_decimal(12.5, scale=2) == Decimal("12.5")

    def test_decimal_passthrough(self):
        assert _parse_decimal(Decimal("1234.56"), scale=2) == Decimal("1234.56")


class TestStringBasics:
    def test_plain_string(self):
        assert _parse_decimal("486000", scale=2) == Decimal("486000")

    def test_comma_separator(self):
        assert _parse_decimal("1,234.56", scale=2) == Decimal("1234.56")

    def test_currency_full_width_yuan(self):
        """全角 ￥"""
        assert _parse_decimal("￥486000", scale=2) == Decimal("486000")

    def test_currency_half_width_yuan(self):
        """半角 ¥"""
        assert _parse_decimal("¥486000", scale=2) == Decimal("486000")

    def test_negative(self):
        assert _parse_decimal("-1234", scale=2) == Decimal("-1234")


class TestSuffixYuan:
    """P0-3 核心:剥"元/万元/万"后缀"""

    def test_yuan_suffix_basic(self):
        """原始 B 家案例"""
        assert _parse_decimal("486000元", scale=2) == Decimal("486000")

    def test_yen_plus_yuan_suffix(self):
        """￥486000元 — 混合符号"""
        assert _parse_decimal("￥486000元", scale=2) == Decimal("486000")

    def test_wan_yuan_suffix(self):
        """万元 × 10000"""
        assert _parse_decimal("12.5万元", scale=2) == Decimal("125000.0")

    def test_wan_suffix(self):
        """仅"万" × 10000"""
        assert _parse_decimal("12.5万", scale=2) == Decimal("125000.0")

    def test_wan_yuan_priority_over_yuan(self):
        """"万元" 必须优先于 "元" 被剥(否则会拆成数字+元)"""
        assert _parse_decimal("50万元", scale=2) == Decimal("500000")

    def test_yuan_with_comma_and_space(self):
        """组合:千分位 + 全角空格 + 元"""
        assert _parse_decimal("1,234.56 元", scale=2) == Decimal("1234.56")

    def test_yuan_with_full_width_space(self):
        """U+3000 全角空格"""
        assert _parse_decimal("1234\u3000元", scale=2) == Decimal("1234")


class TestFailureModes:
    def test_zheng_suffix_not_supported(self):
        """\"12万元整\" 的"整"字未支持 → None(规则明确不扩)"""
        assert _parse_decimal("12万元整", scale=2) is None

    def test_plain_yuan_lowercase_chinese_not_supported(self):
        """\"壹万\" 中文大写不在本 change 范围"""
        assert _parse_decimal("壹万", scale=2) is None

    def test_letters_return_none(self):
        assert _parse_decimal("hello", scale=2) is None

    def test_none_returns_none(self):
        assert _parse_decimal(None, scale=2) is None

    def test_empty_string_returns_none(self):
        assert _parse_decimal("", scale=2) is None

    def test_whitespace_only_returns_none(self):
        assert _parse_decimal("   ", scale=2) is None

    def test_mixed_garbage_returns_none(self):
        assert _parse_decimal("abc 元", scale=2) is None


class TestRegressionExistingBehavior:
    """确保老 case 不回归"""

    def test_comma_1234(self):
        assert _parse_decimal("1,234", scale=2) == Decimal("1234")

    def test_currency_original(self):
        assert _parse_decimal("￥486000", scale=2) == Decimal("486000")

    def test_dollar_strip(self):
        assert _parse_decimal("$100", scale=2) == Decimal("100")

    def test_scientific_notation_unsupported(self):
        """科学计数仍未支持(既有行为)"""
        assert _parse_decimal("1e3", scale=2) is None
