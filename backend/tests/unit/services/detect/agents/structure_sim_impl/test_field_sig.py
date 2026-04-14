"""L1 - C9 field_sig(字段结构维度)"""

from __future__ import annotations

from app.services.detect.agents.structure_sim_impl import field_sig
from app.services.detect.agents.structure_sim_impl.field_sig import SheetInput


def test_cell_nonempty():
    assert field_sig._cell_nonempty("abc")
    assert field_sig._cell_nonempty(0)
    assert field_sig._cell_nonempty(False)
    assert not field_sig._cell_nonempty(None)
    assert not field_sig._cell_nonempty("")
    assert not field_sig._cell_nonempty("   ")


def test_extract_header_tokens_normalizes_ascii():
    rows = [[None, "  "], ["Name", "QTY", "Price"], ["x", 1, 2]]
    tokens = field_sig._extract_header_tokens(rows)
    assert tokens == ["name", "qty", "price"]


def test_extract_header_tokens_keeps_chinese_raw():
    rows = [["姓名", "数量", "单价"]]
    tokens = field_sig._extract_header_tokens(rows)
    assert tokens == ["姓名", "数量", "单价"]


def test_row_bitmask():
    assert field_sig._row_bitmask([1, None, "a", None]) == "101"
    assert field_sig._row_bitmask([None, None, None]) == "0"
    assert field_sig._row_bitmask(["x", "y", "z"]) == "111"


def test_jaccard_set():
    assert field_sig._jaccard_set({"a", "b"}, {"a", "b"}) == 1.0
    assert field_sig._jaccard_set({"a", "b"}, {"a", "c"}) == 1 / 3
    assert field_sig._jaccard_set(set(), set()) == 1.0
    assert field_sig._jaccard_set({"a"}, set()) == 0.0


def test_jaccard_multiset():
    assert field_sig._jaccard_multiset(["a", "b", "a"], ["a", "b", "a"]) == 1.0
    # ["a","a"] vs ["a"] → 交 1, 并 2 → 0.5
    assert field_sig._jaccard_multiset(["a", "a"], ["a"]) == 0.5
    assert field_sig._jaccard_multiset([], []) == 1.0
    assert field_sig._jaccard_multiset(["a"], []) == 0.0


def test_compute_field_similarity_identical_single_sheet():
    rows = [["name", "qty", "price"], ["pump", 10, 500], ["pipe", 2, 12]]
    a = [SheetInput("报价", rows, ["A1:C1"])]
    b = [SheetInput("报价", [r[:] for r in rows], ["A1:C1"])]
    r = field_sig.compute_field_similarity(a, b)
    assert r is not None
    assert r.score == 1.0
    assert len(r.per_sheet) == 1
    ps = r.per_sheet[0]
    assert ps.header_sim == 1.0
    assert ps.bitmask_sim == 1.0
    assert ps.merged_cells_sim == 1.0


def test_compute_field_similarity_completely_different():
    a = [
        SheetInput(
            "S1",
            [["name", "qty"], ["pump", 10], ["pipe", 5]],
            [],
        )
    ]
    b = [
        SheetInput(
            "S1",
            [["title", "author"], ["book1", "x"], ["book2", "y"]],
            [],
        )
    ]
    r = field_sig.compute_field_similarity(a, b)
    assert r is not None
    # headers 完全不同 → header=0;bitmask 都是 "11" 三行 → bitmask=1;merged 都空 → 1.0
    ps = r.per_sheet[0]
    assert ps.header_sim == 0.0
    # score = (0*0.4 + 1*0.3 + 1*0.3) / 1.0 = 0.6
    assert abs(r.score - 0.6) < 1e-4


def test_compute_field_similarity_no_name_overlap():
    """sheet 名不重合 → 没有配对 sheet → None。"""
    a = [SheetInput("报价", [["x", "y"], [1, 2]], [])]
    b = [SheetInput("清单", [["x", "y"], [1, 2]], [])]
    assert field_sig.compute_field_similarity(a, b) is None


def test_compute_field_similarity_multi_sheet_pairing():
    """多 sheet,只同名配对;取 max sub_score。"""
    a = [
        SheetInput("A", [["h1", "h2"], [1, 2], [3, 4]], []),
        SheetInput("B", [["差", "很", "多"], [1, 2, 3], [4, 5, 6]], []),
    ]
    b = [
        SheetInput("A", [["h1", "h2"], [1, 2], [3, 4]], []),  # 完全相同
        SheetInput("B", [["xx", "yy", "zz"], [9, 9, 9], [0, 0, 0]], []),
    ]
    r = field_sig.compute_field_similarity(a, b)
    assert r is not None
    # A sheet 1.0 + B sheet < 1.0 → max=1.0
    assert r.score == 1.0
    assert len(r.per_sheet) == 2


def test_compute_field_similarity_min_rows_filter(monkeypatch):
    """非空行数 < MIN_SHEET_ROWS(默认 2)→ sheet 不参与。"""
    monkeypatch.setenv("STRUCTURE_SIM_MIN_SHEET_ROWS", "3")
    # A sheet 只 2 行 → 被过滤 → valid=0 → None
    a = [SheetInput("A", [["h1"], ["x"]], [])]
    b = [SheetInput("A", [["h1"], ["x"]], [])]
    assert field_sig.compute_field_similarity(a, b) is None


def test_compute_field_similarity_empty_input():
    assert field_sig.compute_field_similarity([], []) is None
    assert (
        field_sig.compute_field_similarity(
            [], [SheetInput("A", [["x"], ["y"]], [])]
        )
        is None
    )


def test_compute_field_similarity_sub_weights_env(monkeypatch):
    """子权重 env 覆盖生效。"""
    monkeypatch.setenv("STRUCTURE_SIM_FIELD_JACCARD_SUB_WEIGHTS", "1.0,0,0")
    # 只看 header → header_sim=1 → sub=1
    a = [SheetInput("A", [["h1", "h2"], [1, 2], [3, 4]], [])]
    # headers 同,bitmask 不同(b 行数多),merged 不同
    b = [SheetInput("A", [["h1", "h2"], [1, None], [None, 2]], ["A1:A3"])]
    r = field_sig.compute_field_similarity(a, b)
    assert r is not None
    assert r.score == 1.0


def test_compute_field_similarity_per_sheet_limit():
    """per_sheet 上限 5,超出按 sub_score 截断。"""
    sheets_a = []
    sheets_b = []
    for i in range(8):
        rows = [["h"], [i]]
        sheets_a.append(SheetInput(f"s{i}", rows, []))
        # i=0 完全不同,其他完全相同 → sub_score 差异
        if i == 0:
            sheets_b.append(SheetInput(f"s{i}", [["XX"], [999]], []))
        else:
            sheets_b.append(SheetInput(f"s{i}", [r[:] for r in rows], []))
    r = field_sig.compute_field_similarity(sheets_a, sheets_b)
    assert r is not None
    assert len(r.per_sheet) == 5  # 截断
    # 前 5 应全 sub_score=1.0(不含 s0)
    assert all(ps.sub_score == 1.0 for ps in r.per_sheet)
