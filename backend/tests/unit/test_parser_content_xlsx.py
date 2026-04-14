"""L1 - parser/content/xlsx_parser 单元测试 (C5 §9.2)"""

from __future__ import annotations

from pathlib import Path

from app.services.parser.content.xlsx_parser import extract_xlsx
from tests.fixtures.doc_fixtures import make_real_xlsx


def test_single_sheet(tmp_path: Path) -> None:
    path = make_real_xlsx(
        tmp_path / "a.xlsx",
        sheets={"数据": [["A", "B"], [1, 2]]},
    )
    result = extract_xlsx(path)
    assert len(result.sheets) == 1
    s = result.sheets[0]
    assert s.sheet_name == "数据"
    assert not s.hidden
    assert "A | B" in s.merged_text


def test_multi_sheet_with_hidden(tmp_path: Path) -> None:
    path = make_real_xlsx(
        tmp_path / "b.xlsx",
        sheets={
            "Visible": [["x"], ["y"]],
            "Hidden": [["h1"], ["h2"]],
        },
        hidden_sheet="Hidden",
    )
    result = extract_xlsx(path)
    assert len(result.sheets) == 2
    by_name = {s.sheet_name: s for s in result.sheets}
    assert by_name["Hidden"].hidden is True
    assert by_name["Visible"].hidden is False


def test_empty_sheet(tmp_path: Path) -> None:
    path = make_real_xlsx(
        tmp_path / "empty.xlsx", sheets={"Empty": [[]]}
    )
    result = extract_xlsx(path)
    assert len(result.sheets) == 1
    # 全空的 sheet merged_text 为空字符串
    assert result.sheets[0].merged_text == ""


def test_rows_preserve_cell_values(tmp_path: Path) -> None:
    path = make_real_xlsx(
        tmp_path / "c.xlsx",
        sheets={"S": [["编码", "单价"], ["A001", 100.5]]},
    )
    result = extract_xlsx(path)
    s = result.sheets[0]
    # rows 的第二行第二个 cell 应当是 100.5(openpyxl 保持数值)
    assert s.rows[1][1] == 100.5
