"""fix-multi-sheet-price-double-count F:数值兜底校验 sheet_role 测试。"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.parser.pipeline.sheet_role_validator import (
    SUM_EQUAL_EPSILON,
    compute_sheet_row_counts,
    compute_sheet_sums,
    find_suspect_pairs,
    validate_sheet_roles,
)


def _pi(sheet_name: str, total_price: Decimal | float | int | None):
    return SimpleNamespace(sheet_name=sheet_name, total_price=total_price)


def test_compute_sheet_sums_groups_by_sheet():
    items = [
        _pi("a", "100"), _pi("a", "200"),
        _pi("b", "50"), _pi("b", "50"),
        _pi("c", None),  # NULL ignore
    ]
    sums = compute_sheet_sums(items)
    assert sums["a"] == Decimal("300")
    assert sums["b"] == Decimal("100")
    assert "c" not in sums or sums["c"] == Decimal("0")


def test_find_suspect_pairs_detects_equal_sums():
    sums = {"a": Decimal("100"), "b": Decimal("100"), "c": Decimal("50")}
    pairs = find_suspect_pairs(sums)
    assert pairs == [("a", "b")]


def test_find_suspect_pairs_skips_zero_sum():
    sums = {"a": Decimal("0"), "b": Decimal("0"), "c": Decimal("100")}
    pairs = find_suspect_pairs(sums)
    assert pairs == []


def test_find_suspect_pairs_within_epsilon():
    """1% 内相等也判 suspect。"""
    sums = {"a": Decimal("100.50"), "b": Decimal("100.00")}  # 0.5% 偏差
    pairs = find_suspect_pairs(sums, epsilon=0.01)
    assert pairs == [("a", "b")]


def test_find_suspect_pairs_outside_epsilon():
    """5% 偏差超出 1% 容差 → 不判。"""
    sums = {"a": Decimal("110"), "b": Decimal("100")}  # 9% 偏差
    pairs = find_suspect_pairs(sums, epsilon=0.01)
    assert pairs == []


def test_validate_监理标_both_main_fixed_to_main_breakdown():
    """监理标:LLM 都标 main + SUM 相等 → 行少为 main, 行多为 breakdown。"""
    cfg = [
        {"sheet_name": "报价表", "sheet_role": "main"},
        {"sheet_name": "管理人员单价表", "sheet_role": "main"},
    ]
    items = [
        _pi("报价表", "456000"),  # 1 行
        _pi("管理人员单价表", "150000"),
        _pi("管理人员单价表", "90000"),
        _pi("管理人员单价表", "60000"),
        _pi("管理人员单价表", "90000"),
        _pi("管理人员单价表", "66000"),  # 5 行 SUM=456000
    ]
    fixed, decisions = validate_sheet_roles(cfg, items)
    by_name = {x["sheet_name"]: x for x in fixed}
    assert by_name["报价表"]["sheet_role"] == "main"  # 行数少
    assert by_name["管理人员单价表"]["sheet_role"] == "breakdown"
    assert len(decisions) == 1
    assert "报价表" in decisions[0] and "管理人员单价表" in decisions[0]


def test_validate_工程量清单_unequal_sums_no_change():
    """工程量清单:三 sheet SUM 不等 → 不动。"""
    cfg = [
        {"sheet_name": "土建", "sheet_role": "main"},
        {"sheet_name": "安装", "sheet_role": "main"},
        {"sheet_name": "电气", "sheet_role": "main"},
    ]
    items = [
        _pi("土建", "100000"),
        _pi("安装", "200000"),
        _pi("电气", "50000"),
    ]
    fixed, decisions = validate_sheet_roles(cfg, items)
    assert decisions == []
    for item in fixed:
        assert item["sheet_role"] == "main"


def test_validate_llm_already_correct_no_change():
    """LLM 已正确给 main+breakdown → 不动。"""
    cfg = [
        {"sheet_name": "a", "sheet_role": "main"},
        {"sheet_name": "b", "sheet_role": "breakdown"},
    ]
    items = [_pi("a", "100"), _pi("b", "50"), _pi("b", "50")]
    fixed, decisions = validate_sheet_roles(cfg, items)
    assert decisions == []
    by_name = {x["sheet_name"]: x for x in fixed}
    assert by_name["a"]["sheet_role"] == "main"
    assert by_name["b"]["sheet_role"] == "breakdown"


def test_validate_single_sheet_no_op():
    cfg = [{"sheet_name": "a", "sheet_role": "main"}]
    items = [_pi("a", "100")]
    fixed, decisions = validate_sheet_roles(cfg, items)
    assert decisions == []
    assert fixed == cfg


def test_validate_empty_config_no_op():
    fixed, decisions = validate_sheet_roles([], [])
    assert decisions == []
    assert fixed == []


def test_validate_equal_rows_equal_sums_default_first_main():
    """边界:两 sheet 行数相等 + SUM 相等 → 字典序首个为 main + warn。"""
    cfg = [
        {"sheet_name": "x", "sheet_role": "main"},
        {"sheet_name": "y", "sheet_role": "main"},
    ]
    items = [
        _pi("x", "50"), _pi("x", "50"),
        _pi("y", "50"), _pi("y", "50"),
    ]
    fixed, decisions = validate_sheet_roles(cfg, items)
    assert len(decisions) == 1
    assert "rare" in decisions[0].lower() or "equal-rows" in decisions[0].lower()
    by_name = {x["sheet_name"]: x for x in fixed}
    # x 字典序在前;sorted pair 是 (x, y),"a"=x 行数=b 行数,默认 x → main
    assert by_name["x"]["sheet_role"] == "main"
    assert by_name["y"]["sheet_role"] == "breakdown"


def test_validate_returns_copy_not_mutate_input():
    cfg = [
        {"sheet_name": "a", "sheet_role": "main"},
        {"sheet_name": "b", "sheet_role": "main"},
    ]
    items = [_pi("a", "100"), _pi("b", "50"), _pi("b", "50")]
    fixed, _ = validate_sheet_roles(cfg, items)
    # 原 cfg 不变
    assert cfg[0]["sheet_role"] == "main"
    assert cfg[1]["sheet_role"] == "main"
    # 新 fixed 改了
    by_name = {x["sheet_name"]: x for x in fixed}
    assert by_name["b"]["sheet_role"] == "breakdown"


def test_epsilon_constant():
    assert SUM_EQUAL_EPSILON == 0.01


def test_compute_row_counts():
    items = [
        _pi("a", "1"), _pi("a", "2"), _pi("a", "3"),
        _pi("b", "1"),
    ]
    counts = compute_sheet_row_counts(items)
    assert counts == {"a": 3, "b": 1}
