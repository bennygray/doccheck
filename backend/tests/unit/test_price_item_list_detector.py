"""L1 - price_impl/item_list_detector (C11)"""

from __future__ import annotations

from decimal import Decimal

from app.services.detect.agents.price_impl.config import ItemListConfig
from app.services.detect.agents.price_impl.item_list_detector import (
    detect_item_list_similarity,
    is_same_template,
)


def _row(item_name: str | None, unit_price: Decimal | None, sheet: str,
         row_index: int, idx: int = 0):
    return {
        "price_item_id": idx or row_index,
        "bidder_id": 1,
        "sheet_name": sheet,
        "row_index": row_index,
        "item_name_raw": item_name,
        "item_name_norm": item_name.lower() if item_name else None,
        "unit_price_raw": unit_price,
        "total_price_raw": unit_price,
        "total_price_float": float(unit_price) if unit_price is not None else None,
        "tail_key": None,
    }


def test_is_same_template_true():
    a = {"s1": [_row("a", Decimal("1"), "s1", i) for i in range(3)]}
    b = {"s1": [_row("a", Decimal("1"), "s1", i) for i in range(3)]}
    assert is_same_template(a, b) is True


def test_is_same_template_false_different_sheets():
    a = {"s1": [_row("a", Decimal("1"), "s1", 0)]}
    b = {"s2": [_row("a", Decimal("1"), "s2", 0)]}
    assert is_same_template(a, b) is False


def test_is_same_template_false_different_size():
    a = {"s1": [_row("a", Decimal("1"), "s1", 0)]}
    b = {"s1": [_row("a", Decimal("1"), "s1", 0), _row("b", Decimal("2"), "s1", 1)]}
    assert is_same_template(a, b) is False


def test_phase_1a_position_full_match():
    # 同模板 + 全对齐"同项同价" → strength 1.0,mode=position
    a = {"s1": [_row(f"x{i}", Decimal("100"), "s1", i) for i in range(5)]}
    b = {"s1": [_row(f"x{i}", Decimal("100"), "s1", i) for i in range(5)]}
    cfg = ItemListConfig(threshold=0.95)
    r = detect_item_list_similarity(a, b, cfg)
    assert r["score"] == 1.0
    assert all(h["mode"] == "position" for h in r["hits"])


def test_phase_1a_below_threshold_zero():
    # 同模板 10 行,5 行匹配 → 0.5 < 0.95 阈值 → score=0
    a = {"s1": [_row(f"x{i}", Decimal("100"), "s1", i) for i in range(10)]}
    b_rows = [_row(f"x{i}", Decimal("100"), "s1", i) for i in range(5)] + [
        _row(f"y{i}", Decimal("999"), "s1", i + 5) for i in range(5)
    ]
    b = {"s1": b_rows}
    cfg = ItemListConfig(threshold=0.95)
    r = detect_item_list_similarity(a, b, cfg)
    assert r["score"] == 0.0


def test_phase_1b_item_name_match():
    # 数量不等(20 vs 18)→ 走阶段 1b
    a = {"s1": [_row(f"item{i}", Decimal("1"), "s1", i) for i in range(20)]}
    b = {"s1": [_row(f"item{i}", Decimal("1"), "s1", i) for i in range(18)]}
    cfg = ItemListConfig(threshold=0.95)
    r = detect_item_list_similarity(a, b, cfg)
    # min(20,18)=18 intersect 18 → 1.0
    assert r["score"] == 1.0
    assert all(h["mode"] == "item_name" for h in r["hits"])


def test_phase_1b_both_sides_no_item_name_returns_none():
    a = {"s1": [_row(None, Decimal("1"), "s1", 0)]}
    b = {"s1": [_row(None, Decimal("1"), "s1", 0), _row(None, Decimal("2"), "s1", 1)]}
    # 同 sheet 但条数不同 → 走阶段 1b;两侧 item_name 全空 → score=None
    r = detect_item_list_similarity(a, b, ItemListConfig())
    assert r["score"] is None


def test_same_sheets_different_size_falls_to_1b():
    # sheet_name 集合相同但某 sheet 条数不等 → 不算同模板 → 走阶段 1b
    a = {"s1": [_row(f"x{i}", Decimal("1"), "s1", i) for i in range(3)]}
    b = {"s1": [_row(f"x{i}", Decimal("1"), "s1", i) for i in range(2)]}
    r = detect_item_list_similarity(a, b, ItemListConfig(threshold=0.5))
    # 阶段 1b:names_a=3, names_b=2, intersect=2 → 1.0
    assert r["score"] == 1.0
    assert r["hits"][0]["mode"] == "item_name"


def test_empty_grouped_returns_none():
    r = detect_item_list_similarity({}, {"s1": [_row("x", Decimal("1"), "s1", 0)]},
                                     ItemListConfig())
    assert r["score"] is None
