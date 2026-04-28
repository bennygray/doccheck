"""fix-multi-sheet-price-double-count B:LLM sheet_role 解析 + 默认值兜底。"""

from __future__ import annotations

from app.services.parser.llm.price_rule_detector import (
    VALID_SHEET_ROLES,
    _apply_sheet_role_defaults,
)


_BASE_MAPPING = {
    "code_col": "A",
    "name_col": "B",
    "unit_col": "C",
    "qty_col": "D",
    "unit_price_col": "E",
    "total_price_col": "F",
    "skip_cols": [],
}


def _item(sn: str, role: str | None) -> dict:
    return {
        "sheet_name": sn,
        "sheet_role": role,
        "header_row": 1,
        "column_mapping": dict(_BASE_MAPPING),
    }


def test_valid_roles_enum():
    assert VALID_SHEET_ROLES == frozenset({"main", "breakdown", "summary"})


def test_default_single_sheet_main():
    cfg = [_item("s1", None)]
    _apply_sheet_role_defaults(cfg)
    assert cfg[0]["sheet_role"] == "main"


def test_default_multi_sheet_first_main_others_breakdown():
    cfg = [_item("s1", None), _item("s2", None), _item("s3", None)]
    _apply_sheet_role_defaults(cfg)
    assert cfg[0]["sheet_role"] == "main"
    assert cfg[1]["sheet_role"] == "breakdown"
    assert cfg[2]["sheet_role"] == "breakdown"


def test_keep_explicit_roles():
    """LLM 已给值的项不被覆盖。"""
    cfg = [_item("s1", "main"), _item("s2", "main")]
    _apply_sheet_role_defaults(cfg)
    assert cfg[0]["sheet_role"] == "main"
    assert cfg[1]["sheet_role"] == "main"


def test_partial_default_only_missing():
    """混合:LLM 给一个 breakdown,另一个缺 → 缺的填 main(idx==0)或 breakdown(其他)。"""
    cfg = [_item("s1", "summary"), _item("s2", None)]
    _apply_sheet_role_defaults(cfg)
    assert cfg[0]["sheet_role"] == "summary"  # 保留
    assert cfg[1]["sheet_role"] == "breakdown"  # 多 sheet 默认非首 → breakdown


def test_empty_config():
    """空 sheets_config 不抛错。"""
    cfg: list[dict] = []
    _apply_sheet_role_defaults(cfg)
    assert cfg == []
