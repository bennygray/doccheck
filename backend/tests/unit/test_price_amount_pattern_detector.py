"""L1 - price_impl/amount_pattern_detector (C11)"""

from __future__ import annotations

from decimal import Decimal

from app.services.detect.agents.price_impl.amount_pattern_detector import (
    detect_amount_pattern,
)
from app.services.detect.agents.price_impl.config import AmountPatternConfig


def _row(item_name: str | None, unit_price: Decimal | None, idx: int = 1):
    return {
        "price_item_id": idx,
        "bidder_id": 1,
        "sheet_name": "s",
        "row_index": idx,
        "item_name_raw": item_name,
        "item_name_norm": item_name.lower() if item_name else None,
        "unit_price_raw": unit_price,
        "total_price_raw": unit_price,
        "total_price_float": float(unit_price) if unit_price is not None else None,
        "tail_key": None,
    }


def test_amount_pattern_high_match_rate():
    # A 10 行 / B 10 行,8 对完全一致
    rows_a = [_row(f"item{i}", Decimal("100")) for i in range(10)]
    rows_b = [_row(f"item{i}", Decimal("100")) for i in range(8)] + [
        _row(f"different{i}", Decimal("999"), idx=20 + i) for i in range(2)
    ]
    cfg = AmountPatternConfig(threshold=0.5)
    r = detect_amount_pattern(rows_a, rows_b, cfg)
    # min(10, 10)=10,intersect 8 → 0.8
    assert r["score"] == 0.8


def test_amount_pattern_item_name_variant_no_merge():
    # item_name 不同(NFKC 后仍不同)→ 不匹配
    rows_a = [_row("钢筋φ12", Decimal("100"))]
    rows_b = [_row("φ12 螺纹钢", Decimal("100"))]
    r = detect_amount_pattern(rows_a, rows_b, AmountPatternConfig())
    assert r["score"] == 0.0


def test_amount_pattern_null_item_name_skip():
    # A 全部 item_name=None → pairs_a 空 → score=None
    rows_a = [_row(None, Decimal("100"), idx=i) for i in range(3)]
    rows_b = [_row(f"x{i}", Decimal("100"), idx=10 + i) for i in range(3)]
    r = detect_amount_pattern(rows_a, rows_b, AmountPatternConfig())
    assert r["score"] is None
    assert "有效对" in r["reason"]


def test_amount_pattern_below_threshold_zero():
    # match_rate=0.4 < threshold=0.5 → score=0.0
    rows_a = [_row(f"item{i}", Decimal("100")) for i in range(10)]
    rows_b = [_row(f"item{i}", Decimal("100")) for i in range(4)] + [
        _row(f"unique{i}", Decimal("999"), idx=20 + i) for i in range(6)
    ]
    cfg = AmountPatternConfig(threshold=0.5)
    r = detect_amount_pattern(rows_a, rows_b, cfg)
    assert r["score"] == 0.0
