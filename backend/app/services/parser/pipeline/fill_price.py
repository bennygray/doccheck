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

# parser-accuracy-fixes P1-6:备注长文本行过滤阈值
# 任一 text 字段(code/name/unit)长度 ≥ 此值且其他字段全空 → 判备注行
PRICE_REMARK_SKIP_MIN_LEN = 100


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
    """按规则从 XLSX 抽报价项写 price_items(parser-accuracy-fixes P1-5 多 sheet)。

    - 权威字段 `rule.sheets_config`:多 sheet 候选数组
    - 老 rule 向后兼容:sheets_config=[] 时 fallback 到 {sheet_name, header_row, column_mapping}
    - M3 护栏:rule.status != 'confirmed' 直接返空
    - M1 单 sheet 异常隔离:某 sheet 抛错仅记入 partial_failed_sheets,继续下一 sheet
    """
    import asyncio

    # M3:非 confirmed 态不回填
    if rule.status != "confirmed":
        logger.warning(
            "fill_price called with non-confirmed rule status=%s bidder=%d",
            rule.status, bidder_id,
        )
        return FillResult()

    # 读 sheets_config(权威);老 rule fallback 到 3 列
    sheets_config = list(rule.sheets_config or [])
    if not sheets_config:
        if rule.column_mapping and rule.sheet_name and rule.header_row:
            sheets_config = [
                {
                    "sheet_name": rule.sheet_name,
                    "header_row": rule.header_row,
                    "column_mapping": rule.column_mapping,
                }
            ]
        else:
            logger.warning(
                "fill_price: rule has neither sheets_config nor legacy fields, bidder=%d",
                bidder_id,
            )
            return FillResult()

    try:
        extracted = await asyncio.to_thread(extract_xlsx, xlsx_path)
    except Exception as e:
        logger.warning("fill_price: xlsx read failed: %s", e)
        return FillResult()

    result = FillResult()

    # 遍历 sheets_config 每项,找对应 sheet 处理
    for cfg in sheets_config:
        target_sheet_name = cfg.get("sheet_name")
        header_row = cfg.get("header_row") or 1
        mapping = cfg.get("column_mapping") or {}

        matching_sheets = [
            s for s in extracted.sheets if s.sheet_name == target_sheet_name
        ]
        if not matching_sheets:
            # LLM 识别的 sheet 在本 xlsx 不存在(可能供应商用了不同表名)
            logger.info(
                "fill_price: sheet %r not found in xlsx, bidder=%d",
                target_sheet_name, bidder_id,
            )
            result.partial_failed_sheets.append(f"{target_sheet_name}:未找到")
            continue

        # M1 单 sheet 异常隔离 + review H3 修:SAVEPOINT 防中途抛异常后该 sheet 部分行残留
        # 每 sheet 一个 savepoint,异常 rollback 该 savepoint(把已 add 的 item 清干净)
        sheet_items_start = result.items_count
        try:
            async with session.begin_nested():
                sheet = matching_sheets[0]
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

            # savepoint 正常结束(commit 到外层事务)
            if sheet_ok:
                result.succeeded_sheets.append(sheet.sheet_name)
            else:
                result.partial_failed_sheets.append(sheet.sheet_name)
        except Exception:
            # savepoint 已自动 rollback;该 sheet 中途 add 的 item 不入库
            # 回退 items_count 计数到进入该 sheet 前的值
            result.items_count = sheet_items_start
            logger.exception(
                "fill_price sheet %r failed, bidder=%d",
                target_sheet_name, bidder_id,
            )
            result.partial_failed_sheets.append(f"{target_sheet_name}:异常")
            continue

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

    # parser-accuracy-fixes P1-6 (review M1):备注 sentinel 短词 skip
    # item_code 以"备注"开头(含"备注:"/"备注:"/"备注1"等短词)+ 数值字段全空 → skip
    # 比长文本规则更激进,兜住 golden 里"item_code='备注:' 3字" 的污染 case
    if item_code and str(item_code).lstrip().startswith("备注"):
        num_all_empty = all(x is None for x in (qty_raw, up_raw, tp_raw))
        if num_all_empty:
            return None

    # parser-accuracy-fixes P1-6 (H3):备注长文本行过滤
    # 扫三个 text 字段(item_code/item_name/unit),任一长度 ≥ PRICE_REMARK_SKIP_MIN_LEN
    # 且其他 5 字段全空(text 空串或 None、num 全 None)→ 判备注污染,skip
    text_fields = {"item_code": item_code, "item_name": item_name, "unit": unit}
    num_fields = [qty_raw, up_raw, tp_raw]
    for k, v in text_fields.items():
        if v and len(str(v)) >= PRICE_REMARK_SKIP_MIN_LEN:
            others_text_empty = all(
                (tv is None or str(tv).strip() == "")
                for tk, tv in text_fields.items() if tk != k
            )
            others_num_empty = all(x is None for x in num_fields)
            if others_text_empty and others_num_empty:
                return None

    # parser-accuracy-fixes P1-7:item_code 序号列识别
    # 若 item_code 匹配 ^\d+$(纯数字整数)且本行其他字段至少一个非空 → 判序号列污染,置空
    if item_code and re.fullmatch(r"\d+", str(item_code).strip()):
        has_other = any(
            v is not None for v in (item_name, unit, qty_raw, up_raw, tp_raw)
        )
        if has_other:
            item_code = None

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

# parser-accuracy-fixes P0-3:中文数值后缀 + 倍率
# 顺序重要:长 suffix 优先匹配(否则 "万元" 会被 "元" 抢走)
_SUFFIX_MULTIPLIERS = [
    ("万元", Decimal("10000")),
    ("万", Decimal("10000")),
    ("元", Decimal("1")),
]


def _parse_decimal(raw: object | None, scale: int) -> Decimal | None:
    """归一化数值:去千分位 / 货币符号 / 元-万元-万 中文后缀。归一失败返 None。

    parser-accuracy-fixes P0-3:扩 "元/万元/万" 后缀;"万"/"万元" × 10000。
    """
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
    # 去货币符号 / 千分位 / 空格(含全角空格 \u3000)
    cleaned = (
        s.replace(",", "")
        .replace("￥", "")  # 全角
        .replace("¥", "")   # 半角
        .replace("$", "")
        .replace(" ", "")
        .replace("\u3000", "")  # 全角空格
    )
    # 剥中文后缀(长优先)
    multiplier = Decimal("1")
    for suffix, mult in _SUFFIX_MULTIPLIERS:
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            multiplier = mult
            break
    if not _NUMBER_RE.match(cleaned):
        return None
    try:
        return Decimal(cleaned) * multiplier
    except InvalidOperation:
        return None


__all__ = ["fill_price_from_rule", "FillResult"]
