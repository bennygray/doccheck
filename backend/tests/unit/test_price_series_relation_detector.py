"""L1 - price_impl/series_relation_detector (C11)"""

from __future__ import annotations

from decimal import Decimal

from app.services.detect.agents.price_impl.config import SeriesConfig
from app.services.detect.agents.price_impl.series_relation_detector import (
    detect_series_relation,
)


def _row(total_price: Decimal | None, sheet: str, row_index: int):
    return {
        "price_item_id": row_index,
        "bidder_id": 1,
        "sheet_name": sheet,
        "row_index": row_index,
        "item_name_raw": None,
        "item_name_norm": None,
        "unit_price_raw": None,
        "total_price_raw": total_price,
        "total_price_float": float(total_price) if total_price is not None else None,
        "tail_key": None,
    }


def test_series_ratio_match():
    # B = A × 0.95(5 行)→ ratios=[0.95]*5 方差 0
    a_vals = [Decimal("100"), Decimal("200"), Decimal("300"), Decimal("400"), Decimal("500")]
    b_vals = [v * Decimal("0.95") for v in a_vals]
    a = {"s1": [_row(v, "s1", i) for i, v in enumerate(a_vals)]}
    b = {"s1": [_row(v, "s1", i) for i, v in enumerate(b_vals)]}
    r = detect_series_relation(a, b, SeriesConfig())
    assert r["score"] == 1.0
    ratio_hit = next(h for h in r["hits"] if h["mode"] == "ratio")
    assert ratio_hit["k"] == 0.95
    assert ratio_hit["pairs"] == 5


def test_series_diff_match():
    # diffs=[10000]*5 mean=10000 stdev=0 → CV=0
    a_vals = [Decimal("100000"), Decimal("200000"), Decimal("150000"), Decimal("180000"), Decimal("220000")]
    b_vals = [v + Decimal("10000") for v in a_vals]
    a = {"s1": [_row(v, "s1", i) for i, v in enumerate(a_vals)]}
    b = {"s1": [_row(v, "s1", i) for i, v in enumerate(b_vals)]}
    r = detect_series_relation(a, b, SeriesConfig())
    # 等差命中(diff CV=0);ratio 不一定命中(各 ratio 不同)
    diff_hits = [h for h in r["hits"] if h["mode"] == "diff"]
    assert len(diff_hits) == 1
    assert diff_hits[0]["diff"] == 10000.00
    assert r["score"] == 1.0


def test_series_no_match_for_independent_quotes():
    # 各种乱七八糟比例
    a_vals = [Decimal("100"), Decimal("200"), Decimal("300"), Decimal("400"), Decimal("500")]
    b_vals = [Decimal("85"), Decimal("220"), Decimal("276"), Decimal("460"), Decimal("440")]
    a = {"s1": [_row(v, "s1", i) for i, v in enumerate(a_vals)]}
    b = {"s1": [_row(v, "s1", i) for i, v in enumerate(b_vals)]}
    r = detect_series_relation(a, b, SeriesConfig())
    assert r["score"] == 0.0


def test_series_below_min_pairs():
    # 仅 2 行对齐;min_pairs=3 默认 → score=None
    a_vals = [Decimal("100"), Decimal("200")]
    b_vals = [Decimal("95"), Decimal("190")]
    a = {"s1": [_row(v, "s1", i) for i, v in enumerate(a_vals)]}
    b = {"s1": [_row(v, "s1", i) for i, v in enumerate(b_vals)]}
    r = detect_series_relation(a, b, SeriesConfig(min_pairs=3))
    assert r["score"] is None
    assert "对齐样本不足" in r["reason"]


def test_series_not_same_template_returns_none():
    a = {"s1": [_row(Decimal("100"), "s1", 0)]}
    b = {"s2": [_row(Decimal("95"), "s2", 0)]}
    r = detect_series_relation(a, b, SeriesConfig())
    assert r["score"] is None
    assert "非同模板" in r["reason"]


def test_series_skips_zero_a_and_none():
    # a=0 → 跳过该行;a=None → 跳过该行
    a_vals = [Decimal("0"), None, Decimal("100"), Decimal("200"), Decimal("300"),
              Decimal("400")]
    b_vals = [Decimal("95"), Decimal("190"), Decimal("95"), Decimal("190"),
              Decimal("285"), Decimal("380")]
    a = {"s1": [_row(v, "s1", i) for i, v in enumerate(a_vals)]}
    b = {"s1": [_row(v, "s1", i) for i, v in enumerate(b_vals)]}
    r = detect_series_relation(a, b, SeriesConfig(min_pairs=3))
    # 跳掉 a=0 和 a=None 的行,剩 4 行,ratios=[0.95]*4 方差 0 → 命中
    assert r["score"] == 1.0
