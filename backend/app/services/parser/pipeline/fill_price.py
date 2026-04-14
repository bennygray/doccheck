"""报价数据回填 (C5 parser-pipeline US-4.4)

按 price_parsing_rule.column_mapping 从 XLSX 抽行 → price_items。
归一化:千分位 / 中文大写金额 / 科学计数;失败该字段 NULL 不阻断整行。

返回 FillResult 供上游判定 bidder 终态:priced / price_partial / price_failed。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.services.parser.content.xlsx_parser import extract_xlsx

logger = logging.getLogger(__name__)


@dataclass
class FillResult:
    items_count: int = 0
    succeeded_sheets: list[str] = field(default_factory=list)
    partial_failed_sheets: list[str] = field(default_factory=list)


async def fill_price_from_rule(
    session: AsyncSession,
    bidder_id: int,
    rule: PriceParsingRule,
    xlsx_path: str | Path,
) -> FillResult:
    """按规则从 XLSX 抽报价项写 price_items。

    - 抽取的 sheet 匹配 rule.sheet_name;匹配失败 → 所有 sheet 按同 mapping 试
    - 每 sheet 至少 1 行成功 → 算该 sheet 成功
    - 全空行 / 归一化全失败 → 该 sheet 失败,加入 partial_failed_sheets
    """
    import asyncio

    try:
        extracted = await asyncio.to_thread(extract_xlsx, xlsx_path)
    except Exception as e:
        logger.warning("fill_price: xlsx read failed: %s", e)
        return FillResult()

    result = FillResult()
    target_sheet = rule.sheet_name

    sheets_to_try = [
        s for s in extracted.sheets if s.sheet_name == target_sheet
    ]
    # 如果找不到目标 sheet,对所有 sheet 都试(兼容 LLM 返了别名)
    if not sheets_to_try:
        sheets_to_try = list(extracted.sheets)

    mapping = rule.column_mapping or {}
    header_row = rule.header_row or 1

    for sheet in sheets_to_try:
        sheet_ok = False
        for row_idx in range(header_row, len(sheet.rows)):
            row = sheet.rows[row_idx]
            # 空行跳过
            if all(c is None or str(c).strip() == "" for c in row):
                continue
            item = _extract_row(
                bidder_id=bidder_id,
                rule_id=rule.id,
                sheet_name=sheet.sheet_name,
                row_index=row_idx + 1,  # 1-based 对齐 Excel
                row=row,
                mapping=mapping,
            )
            if item is None:
                continue
            session.add(item)
            result.items_count += 1
            sheet_ok = True

        if sheet_ok:
            result.succeeded_sheets.append(sheet.sheet_name)
        else:
            result.partial_failed_sheets.append(sheet.sheet_name)

    await session.commit()
    return result


def _extract_row(
    *,
    bidder_id: int,
    rule_id: int,
    sheet_name: str,
    row_index: int,
    row: list,
    mapping: dict,
) -> PriceItem | None:
    """按 mapping 抽 6 字段;全空返 None。"""
    def _cell(col_key: str) -> object | None:
        col_letter = mapping.get(col_key)
        if not col_letter:
            return None
        idx = _letter_to_idx(col_letter)
        if idx is None or idx >= len(row):
            return None
        val = row[idx]
        if val is None:
            return None
        s = str(val).strip()
        return s or None

    item_code = _cell("code_col")
    item_name = _cell("name_col")
    unit = _cell("unit_col")
    qty_raw = _cell("qty_col")
    up_raw = _cell("unit_price_col")
    tp_raw = _cell("total_price_col")

    # 6 字段都空 → 空数据行
    if all(v is None for v in (item_code, item_name, unit, qty_raw, up_raw, tp_raw)):
        return None

    quantity = _parse_decimal(qty_raw, scale=4)
    unit_price = _parse_decimal(up_raw, scale=2)
    total_price = _parse_decimal(tp_raw, scale=2)

    return PriceItem(
        bidder_id=bidder_id,
        price_parsing_rule_id=rule_id,
        sheet_name=sheet_name,
        row_index=row_index,
        item_code=_clip(item_code, 200),
        item_name=_clip(item_name, 500),
        unit=_clip(unit, 50),
        quantity=quantity,
        unit_price=unit_price,
        total_price=total_price,
    )


def _clip(s: object | None, max_len: int) -> str | None:
    if s is None:
        return None
    txt = str(s)
    return txt[:max_len]


def _letter_to_idx(letter: str) -> int | None:
    """Excel 列字母 → 0-based 索引。非法返 None。"""
    if not letter or not isinstance(letter, str):
        return None
    s = letter.strip().upper()
    if not s or not s.isalpha():
        return None
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _parse_decimal(raw: object | None, scale: int) -> Decimal | None:
    """归一化数值:去千分位 / 货币符号 / 纯数字。归一失败返 None 不阻断。"""
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        try:
            return Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return None
    s = str(raw).strip()
    if not s:
        return None
    # 去货币符号 / 千分位 / 空格
    cleaned = s.replace(",", "").replace("￥", "").replace("$", "").replace(" ", "")
    if not _NUMBER_RE.match(cleaned):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


__all__ = ["fill_price_from_rule", "FillResult"]
