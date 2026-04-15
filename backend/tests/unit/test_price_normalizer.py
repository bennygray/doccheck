"""L1 - price_impl/normalizer (C11)"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.detect.agents.price_impl.normalizer import (
    decimal_to_float_safe,
    normalize_item_name,
    split_price_tail,
)


# --------- normalize_item_name ---------


def test_normalize_item_name_none():
    assert normalize_item_name(None) is None


def test_normalize_item_name_empty():
    assert normalize_item_name("") is None
    assert normalize_item_name("   ") is None


def test_normalize_item_name_nfkc_fullwidth():
    # 全角 Φ → 半角 φ;casefold
    assert normalize_item_name("钢筋Φ12") == "钢筋φ12"


def test_normalize_item_name_casefold():
    assert normalize_item_name("ABC") == "abc"


def test_normalize_item_name_strip():
    assert normalize_item_name("  hello  ") == "hello"


# --------- split_price_tail ---------


def test_split_tail_combination_distinguishes_magnitude():
    # 100 → tail "100" int_len 3
    assert split_price_tail(Decimal("100"), 3) == ("100", 3)
    # 1100 → tail "100" int_len 4(同尾不同量级)
    assert split_price_tail(Decimal("1100"), 3) == ("100", 4)
    # 8100 → tail "100" int_len 4
    assert split_price_tail(Decimal("8100"), 3) == ("100", 4)


def test_split_tail_int_truncate():
    # int(Decimal('1000.99')) == 1000(truncate 不四舍五入)
    assert split_price_tail(Decimal("1000.99"), 3) == ("000", 4)


def test_split_tail_negative_returns_none():
    assert split_price_tail(Decimal("-50"), 3) is None


def test_split_tail_none_returns_none():
    assert split_price_tail(None, 3) is None


def test_split_tail_zfill_small_number():
    # 99 < tail_n=3 → zfill 到 3 位 "099";int_len 仍 2
    assert split_price_tail(Decimal("99"), 3) == ("099", 2)


def test_split_tail_n_4_variation():
    assert split_price_tail(Decimal("12345"), 4) == ("2345", 5)


# --------- decimal_to_float_safe ---------


def test_decimal_to_float_safe_none():
    assert decimal_to_float_safe(None) is None


def test_decimal_to_float_safe_normal():
    assert decimal_to_float_safe(Decimal("123.45")) == pytest.approx(123.45)


def test_decimal_to_float_safe_zero():
    assert decimal_to_float_safe(Decimal("0")) == 0.0
