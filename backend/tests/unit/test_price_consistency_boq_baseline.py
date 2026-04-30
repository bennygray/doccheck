"""L1 - price_consistency baseline 接入(detect-tender-baseline §5.4)

覆盖 spec ADD Req "BOQ 项级 baseline hash" + "4 高优 detector 接入 baseline 注入点":
- BOQ 项级命中 → 行从 detector 输入剔除(item_list / amount_pattern / tail / series 全 0 侵入)
- 不含价格(单价不参与 hash 比对,boq_baseline_hash 由 parser 写入)
- 多 xlsx 合并:多 sheet → 同一 baseline_set 跨 sheet 过滤
- 工程量精度(由 hash 计算阶段保证,本测试只验 filter 行为)
- BOQ_DIMENSIONS L1 only:无 L2 共识(由 baseline_resolver 保证,本层只 fail-soft)
- 老调用兼容:boq_baseline_hash NULL 时不剔除(老数据不假阳)
"""

from __future__ import annotations

from app.services.detect.agents.price_consistency import (
    _filter_grouped_by_baseline,
)


def _row(price_item_id: int, *, sheet: str = "s1", row_index: int = 1,
         boq_hash: str | None = None) -> dict:
    """最小 PriceRow 构造(只填 filter 用字段)。"""
    return {
        "price_item_id": price_item_id,
        "bidder_id": 1,
        "sheet_name": sheet,
        "row_index": row_index,
        "item_name_raw": "建设工程委托监理",
        "item_name_norm": "建设工程委托监理",
        "unit_price_raw": None,
        "total_price_raw": None,
        "total_price_float": None,
        "tail_key": None,
        "boq_baseline_hash": boq_hash,
    }


# ============================================================ baseline 集合命中过滤


def test_filter_by_baseline_full_match_excludes_all():
    """grouped 中所有行 boq_baseline_hash ∈ baseline → 全部剔除,grouped 变空。"""
    grouped = {
        "s1": [_row(1, boq_hash="h1"), _row(2, boq_hash="h2")],
        "s2": [_row(3, boq_hash="h1")],
    }
    baseline = {"h1", "h2"}
    filtered, excluded = _filter_grouped_by_baseline(grouped, baseline)
    assert filtered == {}, "全命中 → grouped MUST 为空(空 sheet 也剔除)"
    assert excluded == 3


def test_filter_by_baseline_partial_match_keeps_unmatched():
    """部分命中 → 仅剔除 baseline 行,保留非 baseline 行(spec 不豁免整 PC)。"""
    grouped = {
        "s1": [_row(1, boq_hash="h1"), _row(2, boq_hash="h_other")],
        "s2": [_row(3, boq_hash="h2"), _row(4, boq_hash=None)],
    }
    baseline = {"h1"}
    filtered, excluded = _filter_grouped_by_baseline(grouped, baseline)
    # h1 (price_item_id=1) 被剔除,其余保留
    kept_ids = {r["price_item_id"] for rows in filtered.values() for r in rows}
    assert kept_ids == {2, 3, 4}
    assert excluded == 1


def test_filter_by_baseline_empty_baseline_short_circuit():
    """空 baseline 集 → 直接返原 grouped + 0,零开销短路(不复制 dict)。"""
    grouped = {"s1": [_row(1, boq_hash="h1")]}
    filtered, excluded = _filter_grouped_by_baseline(grouped, set())
    assert filtered is grouped, "空 baseline 应直接返原 dict 引用,不构造新 dict"
    assert excluded == 0


def test_filter_by_baseline_null_hash_not_excluded():
    """boq_baseline_hash=NULL(老数据 / 不完整行)→ 不剔除(fail-soft 不假阳)。"""
    grouped = {
        "s1": [_row(1, boq_hash=None), _row(2, boq_hash="h1")],
    }
    baseline = {"h1"}
    filtered, excluded = _filter_grouped_by_baseline(grouped, baseline)
    kept_ids = {r["price_item_id"] for rows in filtered.values() for r in rows}
    assert kept_ids == {1}, "NULL hash MUST 保留;只 hash ∈ baseline 才剔除"
    assert excluded == 1


def test_filter_by_baseline_empty_sheet_dropped():
    """sheet 内所有行被剔除 → 该 sheet key 也从 filtered dict 中剔除(避免空 sheet 噪音)。"""
    grouped = {
        "s1": [_row(1, boq_hash="h1")],
        "s2": [_row(2, boq_hash="h_other")],
    }
    baseline = {"h1"}
    filtered, _ = _filter_grouped_by_baseline(grouped, baseline)
    assert "s1" not in filtered, "全剔除的 sheet MUST 不在 filtered 内"
    assert "s2" in filtered


def test_filter_by_baseline_multi_sheet_unified_baseline():
    """多 xlsx → 多 sheet:同一 baseline_set 跨 sheet 过滤(spec scenario "多份 BOQ xlsx 合并基线")。"""
    grouped = {
        "工程量清单": [_row(1, boq_hash="h_tender_1"), _row(2, boq_hash="h_unique_a")],
        "其他清单": [_row(3, boq_hash="h_tender_2"), _row(4, boq_hash="h_unique_b")],
    }
    baseline = {"h_tender_1", "h_tender_2"}  # 跨多 xlsx 合并的 tender hash
    filtered, excluded = _filter_grouped_by_baseline(grouped, baseline)
    kept_ids = {r["price_item_id"] for rows in filtered.values() for r in rows}
    assert kept_ids == {2, 4}, "跨 sheet 应统一应用 baseline"
    assert excluded == 2


def test_filter_by_baseline_no_match_returns_all_rows():
    """baseline_set 与 grouped hash 完全不重合 → 不剔除任何行。"""
    grouped = {
        "s1": [_row(1, boq_hash="h_a"), _row(2, boq_hash="h_b")],
    }
    baseline = {"h_x", "h_y"}
    filtered, excluded = _filter_grouped_by_baseline(grouped, baseline)
    kept_ids = {r["price_item_id"] for rows in filtered.values() for r in rows}
    assert kept_ids == {1, 2}
    assert excluded == 0


def test_filter_by_baseline_preserves_row_order():
    """filter 保留 sheet 内行的原顺序(detector 行级对齐依赖序)。"""
    grouped = {
        "s1": [
            _row(1, row_index=10, boq_hash=None),
            _row(2, row_index=20, boq_hash="h_baseline"),
            _row(3, row_index=30, boq_hash=None),
            _row(4, row_index=40, boq_hash="h_baseline"),
            _row(5, row_index=50, boq_hash=None),
        ],
    }
    filtered, _ = _filter_grouped_by_baseline(grouped, {"h_baseline"})
    kept = filtered["s1"]
    assert [r["price_item_id"] for r in kept] == [1, 3, 5]
    assert [r["row_index"] for r in kept] == [10, 30, 50]


def test_filter_by_baseline_independent_per_grouped_dict():
    """连续两次调用使用不同 baseline_set,不互相污染。"""
    grouped = {"s1": [_row(1, boq_hash="h1"), _row(2, boq_hash="h2")]}
    f1, e1 = _filter_grouped_by_baseline(grouped, {"h1"})
    f2, e2 = _filter_grouped_by_baseline(grouped, {"h2"})
    assert e1 == 1 and e2 == 1
    kept1 = {r["price_item_id"] for rows in f1.values() for r in rows}
    kept2 = {r["price_item_id"] for rows in f2.values() for r in rows}
    assert kept1 == {2}
    assert kept2 == {1}
    # 原 grouped 不被修改
    assert len(grouped["s1"]) == 2
