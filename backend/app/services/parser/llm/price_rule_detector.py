"""LLM 报价表结构识别 (C5 parser-pipeline US-4.4 + parser-accuracy-fixes P1-5)

给定一个 XLSX 文件,把**所有**候选价格 sheet 的前 ~8 行预览喂 LLM,
识别 sheets_config(数组,每项 sheet_name + header_row + column_mapping)。

返回 None = 识别失败(上游 rule_coordinator 据此写 status='failed')。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
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

# fix-multi-sheet-price-double-count B:sheet_role 三值枚举
VALID_SHEET_ROLES: frozenset[str] = frozenset({"main", "breakdown", "summary"})

_PREVIEW_ROWS = 8


@dataclass(frozen=True)
class PriceRuleDraft:
    # parser-accuracy-fixes P1-5:多 sheet 候选;sheets_config 是新权威字段
    sheets_config: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        # review M2:sheets_config 必须非空;detect_price_rule 在空时已返 None,
        # 此处做 invariant guard 防未来 refactor 引入空 draft 隐式污染老 3 列回写
        if not self.sheets_config:
            raise ValueError(
                "PriceRuleDraft.sheets_config must be non-empty; "
                "detect_price_rule should return None instead"
            )

    @property
    def first_sheet_name(self) -> str:
        return self.sheets_config[0]["sheet_name"]

    @property
    def first_header_row(self) -> int:
        return self.sheets_config[0]["header_row"]

    @property
    def first_column_mapping(self) -> dict[str, Any]:
        return self.sheets_config[0]["column_mapping"]


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

    # parser-accuracy-fixes P1-5:把**所有** sheet 的预览塞 prompt,LLM 自己筛候选
    sheets_block_parts: list[str] = []
    for sheet in result.sheets:
        preview_lines: list[str] = []
        for r_idx, row in enumerate(sheet.rows[:_PREVIEW_ROWS], start=1):
            cells = []
            for c_idx, val in enumerate(row):
                col_letter = _col_letter(c_idx)
                s = "" if val is None else str(val).strip()
                cells.append(f"{col_letter}={s}")
            preview_lines.append(f"  行{r_idx}: " + " | ".join(cells))
        sheets_block_parts.append(
            f"=== sheet: {sheet.sheet_name} ===\n" + "\n".join(preview_lines)
        )
    sheets_block = "\n\n".join(sheets_block_parts)

    user_msg = PRICE_RULE_USER_TEMPLATE.format(
        preview_rows=_PREVIEW_ROWS,
        sheets_block=sheets_block,
    )

    llm_result = await llm.complete(
        messages=[
            {"role": "system", "content": PRICE_RULE_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )

    if llm_result.error is not None:
        # harden-async-infra N7:parser 层(非 agent),不抛 AgentSkippedError。
        # 返 None 让 price_consistency agent 走既有"找不到表头"preflight skip,
        # 精细化 kind 日志供 N3 explore 分析根因。
        logger.warning(
            "price_rule_detector LLM error kind=%s msg=%s",
            llm_result.error.kind,
            llm_result.error.message,
        )
        return None

    parsed = _parse_llm_json(llm_result.text)
    if parsed is None:
        logger.warning(
            "price_rule_detector: invalid JSON raw_text_head=%r",
            (llm_result.text or "")[:200],
        )
        return None

    # 兼容:LLM 返新 schema {sheets_config: [...]} 或老 schema {sheet_name, header_row, column_mapping}
    raw_sheets = parsed.get("sheets_config")
    if raw_sheets is None:
        # 老 format 包装为单 sheet
        old_sheet_name = parsed.get("sheet_name")
        old_header = parsed.get("header_row")
        old_mapping = parsed.get("column_mapping")
        if not all([old_sheet_name, old_header, isinstance(old_mapping, dict)]):
            logger.warning("price_rule_detector: neither sheets_config nor legacy fields")
            return None
        raw_sheets = [
            {
                "sheet_name": old_sheet_name,
                "header_row": old_header,
                "column_mapping": old_mapping,
            }
        ]

    if not isinstance(raw_sheets, list) or not raw_sheets:
        logger.warning("price_rule_detector: sheets_config empty or not list")
        return None

    sheets_config: list[dict[str, Any]] = []
    for item in raw_sheets:
        if not isinstance(item, dict):
            continue
        sn = item.get("sheet_name")
        hr = item.get("header_row")
        cm = item.get("column_mapping")
        if not isinstance(sn, str) or not sn:
            continue
        if not isinstance(hr, int) or hr < 1:
            logger.warning("price_rule_detector: bad header_row=%r sheet=%r", hr, sn)
            continue
        if not isinstance(cm, dict):
            continue
        missing = REQUIRED_MAPPING_KEYS - set(cm.keys())
        if missing:
            logger.warning(
                "price_rule_detector: missing keys %s in sheet %r", missing, sn
            )
            continue
        # 规范化 skip_cols
        if "skip_cols" not in cm or not isinstance(cm["skip_cols"], list):
            cm["skip_cols"] = []
        # fix-multi-sheet-price-double-count B:sheet_role 解析 + enum 校验
        # invalid 或缺失 → 暂置 None,后续 _apply_sheet_role_defaults 兜底
        raw_role = item.get("sheet_role")
        if raw_role is None:
            sheet_role: str | None = None
        elif isinstance(raw_role, str) and raw_role in VALID_SHEET_ROLES:
            sheet_role = raw_role
        else:
            logger.warning(
                "price_rule_detector: invalid sheet_role=%r sheet=%r → default later",
                raw_role, sn,
            )
            sheet_role = None
        sheets_config.append(
            {
                "sheet_name": sn,
                "sheet_role": sheet_role,  # 可能 None,下面统一兜底
                "header_row": hr,
                "column_mapping": cm,
            }
        )

    if not sheets_config:
        logger.warning("price_rule_detector: no valid sheets after validation")
        return None

    # fix-multi-sheet-price-double-count B:sheet_role 缺失兜底
    # 单 sheet:默认 main(zero risk)
    # 多 sheet:第一个 main,后续 breakdown(常见"主表+明细"模式 last-resort)
    _apply_sheet_role_defaults(sheets_config)

    return PriceRuleDraft(sheets_config=sheets_config)


def _apply_sheet_role_defaults(sheets_config: list[dict[str, Any]]) -> None:
    """对 sheet_role 为 None 的项填默认值。原地修改。

    fix-multi-sheet-price-double-count B:LLM 漏 / 非法 sheet_role 时的兜底:
    - 单 sheet:默认 main
    - 多 sheet:第一个 main,后续 breakdown
    LLM 已正确给值的项不被覆盖。
    """
    if not sheets_config:
        return
    if len(sheets_config) == 1:
        if sheets_config[0]["sheet_role"] is None:
            sheets_config[0]["sheet_role"] = "main"
        return
    # 多 sheet:仅对未给值的项填默认
    for idx, item in enumerate(sheets_config):
        if item["sheet_role"] is None:
            item["sheet_role"] = "main" if idx == 0 else "breakdown"


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


__all__ = [
    "detect_price_rule",
    "PriceRuleDraft",
    "REQUIRED_MAPPING_KEYS",
    "VALID_SHEET_ROLES",
]
