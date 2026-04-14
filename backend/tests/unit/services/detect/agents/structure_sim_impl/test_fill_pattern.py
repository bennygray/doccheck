"""L1 - C9 fill_pattern(表单填充模式维度)"""

from __future__ import annotations

import datetime as dt

import pytest

from app.services.detect.agents.structure_sim_impl import fill_pattern
from app.services.detect.agents.structure_sim_impl.field_sig import SheetInput


@pytest.mark.parametrize(
    "cell,expected",
    [
        (None, "_"),
        ("", "_"),
        ("   ", "_"),
        (0, "N"),
        (12345, "N"),
        (3.14, "N"),
        (-1.5, "N"),
        ("123", "N"),
        ("-123.45", "N"),
        ("1,234.56", "N"),
        ("abc", "T"),
        ("投标人", "T"),
        ("2026-04-15", "D"),
        ("2026/4/15", "D"),
        ("2026年4月15日", "D"),
        (dt.datetime(2026, 4, 15), "D"),
        (dt.date(2026, 4, 15), "D"),
        (True, "T"),  # bool → 文本
        (False, "T"),
    ],
)
def test_cell_type_pattern(cell, expected):
    assert fill_pattern.cell_type_pattern(cell) == expected


def test_row_pattern():
    row = ["name", 10, None, "2026-01-01", "xxx"]
    assert fill_pattern._row_pattern(row) == "TN_DT"


def test_compute_fill_similarity_identical():
    rows = [["header", "qty", "price"], ["pump", 10, 500.5], ["pipe", 2, 12]]
    a = [SheetInput("S", rows, [])]
    b = [SheetInput("S", [r[:] for r in rows], [])]
    r = fill_pattern.compute_fill_similarity(a, b)
    assert r is not None
    assert r.score == 1.0
    ps = r.per_sheet[0]
    assert ps.matched_pattern_lines == 3


def test_compute_fill_similarity_same_structure_different_values():
    """不同内容但填充 pattern 相同 → Jaccard 高。"""
    rows_a = [["name", "qty", "price"], ["pump", 10, 500], ["pipe", 2, 12]]
    rows_b = [["物料", "数量", "单价"], ["水泵", 20, 300], ["管材", 5, 40]]
    # 归化 pattern:两者都是 "TTT", "TNN", "TNN"
    a = [SheetInput("S", rows_a, [])]
    b = [SheetInput("S", rows_b, [])]
    r = fill_pattern.compute_fill_similarity(a, b)
    assert r is not None
    assert r.score == 1.0


def test_compute_fill_similarity_completely_different_types():
    rows_a = [["a", "b"], [1, 2], [3, 4]]  # TT, NN, NN
    rows_b = [["x"], ["y"], ["z"]]  # T, T, T(单列)
    a = [SheetInput("S", rows_a, [])]
    b = [SheetInput("S", rows_b, [])]
    r = fill_pattern.compute_fill_similarity(a, b)
    assert r is not None
    # multiset: {TT:1, NN:2} vs {T:3}  → 交 0 → 0.0
    assert r.score == 0.0


def test_compute_fill_similarity_no_name_overlap():
    a = [SheetInput("A", [["x"], ["y"]], [])]
    b = [SheetInput("B", [["x"], ["y"]], [])]
    assert fill_pattern.compute_fill_similarity(a, b) is None


def test_compute_fill_similarity_empty_input():
    assert fill_pattern.compute_fill_similarity([], []) is None


def test_compute_fill_similarity_min_rows_filter(monkeypatch):
    monkeypatch.setenv("STRUCTURE_SIM_MIN_SHEET_ROWS", "5")
    a = [SheetInput("S", [["a"], ["b"]], [])]  # 2 行 < 5
    b = [SheetInput("S", [["a"], ["b"]], [])]
    assert fill_pattern.compute_fill_similarity(a, b) is None


def test_sample_patterns_skip_all_empty():
    """全 '_' pattern(全空行)不出现在 sample_patterns 里。"""
    rows = [["a", "b", "c"], [None, None, None], ["x", "y", "z"]]
    a = [SheetInput("S", rows, [])]
    b = [SheetInput("S", [r[:] for r in rows], [])]
    r = fill_pattern.compute_fill_similarity(a, b)
    assert r is not None
    # 不含 "___"
    assert all(set(p) != {"_"} for p in r.per_sheet[0].sample_patterns)


def test_multi_sheet_max_score():
    a = [
        SheetInput("A", [["x"], ["y"]], []),  # 识 pattern T, T
        SheetInput("B", [["x"], [1], [2]], []),  # T, N, N
    ]
    b = [
        SheetInput("A", [["x"], ["y"]], []),  # 全同
        SheetInput("B", [["x"], ["y"], ["z"]], []),  # T, T, T — 全不同
    ]
    r = fill_pattern.compute_fill_similarity(a, b)
    assert r is not None
    assert r.score == 1.0  # A 相同 → max
