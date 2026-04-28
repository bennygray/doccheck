"""sheet_role='main' SQL 过滤 helper (fix-multi-sheet-price-double-count).

aggregate_bidder_totals 与 compare_price 底部"总报价"行**共用**这个 helper,
保证两处 SUM 数值一致(double-source consistency invariant)。

JSONB 表达式:
  EXISTS (
    SELECT 1 FROM jsonb_array_elements(price_parsing_rules.sheets_config) AS sc
    WHERE sc->>'sheet_name' = price_items.sheet_name
      AND COALESCE(sc->>'sheet_role', 'main') = 'main'
  )

backward compat:老数据(sheets_config 缺 sheet_role 字段)走 COALESCE 默认 'main'
→ 行为同 fix 前(全部 SUM 计入),不破坏既有行为。
"""

from __future__ import annotations

from sqlalchemy import text


def is_main_sheet_clause():
    """返回 SQLAlchemy text expression,用作 query 的 where 条件。

    依赖 query 中已有 ``price_parsing_rules`` 与 ``price_items`` 两表 JOIN.
    """
    return text(
        "EXISTS ("
        "  SELECT 1 FROM jsonb_array_elements(price_parsing_rules.sheets_config) AS sc"
        "  WHERE sc->>'sheet_name' = price_items.sheet_name"
        "    AND COALESCE(sc->>'sheet_role', 'main') = 'main'"
        ")"
    )


__all__ = ["is_main_sheet_clause"]
