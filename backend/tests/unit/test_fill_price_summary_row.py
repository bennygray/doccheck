"""fix-multi-sheet-price-double-count A:汇总行 deterministic skip 测试。

规则修订:item_name 含汇总关键字 + unit_price 为空 → skip。
真分项保护:有 unit_price → 真分项(单价 = 合价/数量),不杀。
"""

from __future__ import annotations

from app.services.parser.pipeline.fill_price import (
    PRICE_SUMMARY_KEYWORDS,
    _extract_row,
)

MAPPING = {
    "code_col": "A",
    "name_col": "B",
    "unit_col": "C",
    "qty_col": "D",
    "unit_price_col": "E",
    "total_price_col": "F",
}


def _row(name: str, qty=None, up=None, tp=None, code=None, unit=None) -> list:
    return [code, name, unit, qty, up, tp]


def test_keyword_合计_no_unit_price_skipped():
    """item_name='合计' + unit_price=None(只有 tp)→ skip(典型监理标 Sheet2 row 9)."""
    item = _extract_row(
        bidder_id=1, rule_id=1, sheet_name="管理人员单价表", row_index=9,
        row=_row("合计", tp="456000"), mapping=MAPPING,
    )
    assert item is None


def test_keyword_合计_with_qty_grand_total_no_up_skipped():
    """实战 case:'合计 qty=28 up=None tp=456000'(qty 是大杂烩)→ skip。"""
    item = _extract_row(
        bidder_id=1, rule_id=1, sheet_name="管理人员单价表", row_index=9,
        row=_row("合计", qty="28", tp="456000"),  # up=None
        mapping=MAPPING,
    )
    assert item is None


def test_keyword_汇总_no_unit_price_skipped():
    item = _extract_row(
        bidder_id=1, rule_id=1, sheet_name="s", row_index=2,
        row=_row("汇总", tp="100000"), mapping=MAPPING,
    )
    assert item is None


def test_all_keywords_skip_when_no_unit_price():
    """每个汇总关键字 + unit_price=None → skip。"""
    for kw in PRICE_SUMMARY_KEYWORDS:
        item = _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=2,
            row=_row(kw, tp="100"), mapping=MAPPING,
        )
        assert item is None, f"keyword {kw!r} should skip"


def test_keyword_prefix_合计费用_no_unit_price_skipped():
    """item_name 以 '合计' 开头(合计费用)+ 仅 total → skip。"""
    item = _extract_row(
        bidder_id=1, rule_id=1, sheet_name="s", row_index=2,
        row=_row("合计费用", tp="100"), mapping=MAPPING,
    )
    assert item is None


def test_real_item_合计费用_with_unit_price_kept():
    """真分项'合计费用' + 有 unit_price → 不杀。"""
    item = _extract_row(
        bidder_id=1, rule_id=1, sheet_name="s", row_index=2,
        row=_row("合计费用", qty="10", up="100", tp="1000"),
        mapping=MAPPING,
    )
    assert item is not None
    assert item.item_name == "合计费用"
    assert str(item.total_price) == "1000"


def test_keyword_with_unit_price_kept():
    """汇总关键字 + 有 unit_price → 真分项,不杀。"""
    item = _extract_row(
        bidder_id=1, rule_id=1, sheet_name="s", row_index=2,
        row=_row("总计", qty="5", up="100", tp="500"), mapping=MAPPING,
    )
    assert item is not None
    assert item.item_name == "总计"


def test_normal_row_unaffected():
    """正常分项行(无汇总关键字)→ 不影响。"""
    item = _extract_row(
        bidder_id=1, rule_id=1, sheet_name="s", row_index=2,
        row=_row("总监理工程师", qty="6", up="25000", tp="150000"),
        mapping=MAPPING,
    )
    assert item is not None
    assert item.item_name == "总监理工程师"
    assert str(item.total_price) == "150000"
