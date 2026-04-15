"""L1 - price_impl/tail_detector (C11)"""

from __future__ import annotations

from decimal import Decimal

from app.services.detect.agents.price_impl.config import TailConfig
from app.services.detect.agents.price_impl.tail_detector import (
    detect_tail_collisions,
)


def _row(price_item_id: int, total_price: Decimal | None, tail_n: int = 3,
         sheet: str = "s1", row_index: int = 1):
    """构造 PriceRow(测试用,跳过 extractor)。"""
    if total_price is None:
        tail_key = None
    else:
        int_val = int(total_price)
        if int_val < 0:
            tail_key = None
        else:
            int_str = str(int_val)
            if len(int_str) >= tail_n:
                tail = int_str[-tail_n:]
            else:
                tail = int_str.zfill(tail_n)
            tail_key = (tail, len(int_str))
    return {
        "price_item_id": price_item_id,
        "bidder_id": 1,
        "sheet_name": sheet,
        "row_index": row_index,
        "item_name_raw": None,
        "item_name_norm": None,
        "unit_price_raw": None,
        "total_price_raw": total_price,
        "total_price_float": float(total_price) if total_price is not None else None,
        "tail_key": tail_key,
    }


def test_tail_collision_3_bidders_pattern():
    # A: 880 / 660 ;  B: 880 / 777
    # set_a={('880',3),('660',3)} set_b={('880',3),('777',3)} ∩={('880',3)} strength=1/2=0.5
    rows_a = [_row(1, Decimal("880")), _row(2, Decimal("660"))]
    rows_b = [_row(3, Decimal("880")), _row(4, Decimal("777"))]
    cfg = TailConfig()
    r = detect_tail_collisions(rows_a, rows_b, cfg)
    assert r["score"] == 0.5
    assert len(r["hits"]) == 1
    assert r["hits"][0]["tail"] == "880"
    assert r["hits"][0]["int_len"] == 3


def test_tail_no_false_positive_across_magnitudes():
    # A: 100(int_len=3),B: 1100(int_len=4)
    # 尾 3 位都是 "100" 但 int_len 不同 → 组合 key 不等
    rows_a = [_row(1, Decimal("100"))]
    rows_b = [_row(2, Decimal("1100"))]
    r = detect_tail_collisions(rows_a, rows_b, TailConfig())
    assert r["score"] == 0.0
    assert r["hits"] == []


def test_tail_all_none_returns_score_none():
    rows_a = [_row(1, None), _row(2, None)]
    rows_b = [_row(3, None)]
    r = detect_tail_collisions(rows_a, rows_b, TailConfig())
    assert r["score"] is None
    assert "无可比对" in r["reason"]


def test_tail_intersect_empty_returns_zero():
    rows_a = [_row(1, Decimal("123"))]
    rows_b = [_row(2, Decimal("456"))]
    r = detect_tail_collisions(rows_a, rows_b, TailConfig())
    assert r["score"] == 0.0


def test_tail_max_hits_limits():
    # 构造 30 个不同 tail key 都能命中,max_hits=5 截断 hits 数
    # 用 Decimal("1100"), "1101", ..., "1129" — 30 个不同尾 3 位 + 同 int_len
    rows_a = [_row(i, Decimal(f"1{i:03d}")) for i in range(100, 130)]
    rows_b = [_row(i + 1000, Decimal(f"1{i:03d}")) for i in range(100, 130)]
    cfg = TailConfig(max_hits=5)
    r = detect_tail_collisions(rows_a, rows_b, cfg)
    assert len(r["hits"]) == 5  # hits 截断到 5 条
    assert r["score"] == 1.0    # 30/30 全部命中
