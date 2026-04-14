"""LLM 报价表结构识别 (C5 parser-pipeline US-4.4)

给定一个 XLSX 文件,选出最像"报价表"的 sheet(优先含"报价/清单"关键字),
取前 ~8 行预览喂 LLM,识别 (sheet_name, header_row, column_mapping)。

返回 None = 识别失败(上游 rule_coordinator 据此写 status='failed')。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.llm.base import LLMProvider
from app.services.parser.content.xlsx_parser import extract_xlsx
from app.services.parser.llm.prompts import (
    PRICE_RULE_SYSTEM_PROMPT,
    PRICE_RULE_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)

REQUIRED_MAPPING_KEYS = {
    "code_col",
    "name_col",
    "unit_col",
    "qty_col",
    "unit_price_col",
    "total_price_col",
}

_PRICE_KEYWORDS = ["报价", "清单", "投标", "工程量"]
_PREVIEW_ROWS = 8


@dataclass(frozen=True)
class PriceRuleDraft:
    sheet_name: str
    header_row: int
    column_mapping: dict[str, Any]


async def detect_price_rule(
    xlsx_path: str | Path,
    llm: LLMProvider,
) -> PriceRuleDraft | None:
    """返回识别结果或 None。任何失败(LLM 错 / JSON 错 / schema 缺键)均返 None。"""
    import asyncio

    try:
        result = await asyncio.to_thread(extract_xlsx, xlsx_path)
    except Exception as e:
        logger.warning("detect_price_rule: xlsx read failed: %s", e)
        return None

    if not result.sheets:
        return None

    # 选最像报价表的 sheet:优先关键字命中,否则取首个
    sheet = _pick_price_sheet(result.sheets)

    # 前 N 行预览(非空 cell 按行拼)
    preview_lines: list[str] = []
    for r_idx, row in enumerate(sheet.rows[:_PREVIEW_ROWS], start=1):
        cells = []
        for c_idx, val in enumerate(row):
            col_letter = _col_letter(c_idx)
            s = "" if val is None else str(val).strip()
            cells.append(f"{col_letter}={s}")
        preview_lines.append(f"行{r_idx}: " + " | ".join(cells))
    preview_block = "\n".join(preview_lines)

    user_msg = PRICE_RULE_USER_TEMPLATE.format(
        sheet_name=sheet.sheet_name,
        preview_rows=min(len(sheet.rows), _PREVIEW_ROWS),
        preview_block=preview_block,
    )

    llm_result = await llm.complete(
        messages=[
            {"role": "system", "content": PRICE_RULE_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )

    if llm_result.error is not None:
        logger.warning(
            "price_rule_detector LLM error kind=%s", llm_result.error.kind
        )
        return None

    parsed = _parse_llm_json(llm_result.text)
    if parsed is None:
        logger.warning("price_rule_detector: invalid JSON from LLM")
        return None

    sheet_name = parsed.get("sheet_name") or sheet.sheet_name
    header_row = parsed.get("header_row")
    column_mapping = parsed.get("column_mapping")

    if not isinstance(header_row, int) or header_row < 1:
        logger.warning("price_rule_detector: invalid header_row=%r", header_row)
        return None
    if not isinstance(column_mapping, dict):
        logger.warning("price_rule_detector: column_mapping not dict")
        return None
    missing = REQUIRED_MAPPING_KEYS - set(column_mapping.keys())
    if missing:
        logger.warning("price_rule_detector: missing keys %s", missing)
        return None

    # 规范化 skip_cols
    if "skip_cols" not in column_mapping:
        column_mapping["skip_cols"] = []
    elif not isinstance(column_mapping["skip_cols"], list):
        column_mapping["skip_cols"] = []

    return PriceRuleDraft(
        sheet_name=str(sheet_name),
        header_row=header_row,
        column_mapping=column_mapping,
    )


def _pick_price_sheet(sheets):
    for sheet in sheets:
        for kw in _PRICE_KEYWORDS:
            if kw in sheet.sheet_name:
                return sheet
    return sheets[0]


def _col_letter(idx: int) -> str:
    """0-based index → Excel 列字母 (0→A, 25→Z, 26→AA)"""
    result = ""
    n = idx
    while True:
        result = chr(ord("A") + n % 26) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            s = "\n".join(lines).strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


__all__ = ["detect_price_rule", "PriceRuleDraft", "REQUIRED_MAPPING_KEYS"]
