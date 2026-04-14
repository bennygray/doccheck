"""C9 字段结构维度:xlsx 每 sheet 列头 + 非空 bitmask + 合并单元格 Jaccard。

三子信号加权(默认子权重 0.4/0.3/0.3),按 sheet_name 配对;
整个字段维度总分 = max(per_sheet.sub_score),一 sheet 雷同即触发。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.services.detect.agents.structure_sim_impl import config
from app.services.detect.agents.structure_sim_impl.models import (
    FieldSimResult,
    SheetFieldResult,
)


@dataclass(frozen=True)
class SheetInput:
    """字段/填充维度的输入(从 DocumentSheet 转换)。"""

    sheet_name: str
    rows: list[list[Any]]
    merged_cells: list[str]


def _cell_nonempty(cell: Any) -> bool:
    if cell is None:
        return False
    return not (isinstance(cell, str) and not cell.strip())


def _extract_header_tokens(rows: list[list[Any]]) -> list[str]:
    """取首个非空行的 cell 归一化列头 token 列表。

    归一化 = 去前后空白、去空字符串、转小写(对英文);中文保留原字符串。
    """
    for row in rows:
        tokens = []
        for c in row:
            if _cell_nonempty(c):
                s = str(c).strip()
                tokens.append(s.lower() if s.isascii() else s)
        if tokens:
            return tokens
    return []


def _row_bitmask(row: list[Any]) -> str:
    """每行按 cell 非空生成 '0'/'1' bitmask 字符串;尾部连续 '0' 截掉。"""
    bits = "".join("1" if _cell_nonempty(c) else "0" for c in row)
    return bits.rstrip("0") or "0"  # 全空行归一到 "0"


def _jaccard_set(a: Iterable, b: Iterable) -> float:
    sa = set(a)
    sb = set(b)
    if not sa and not sb:
        return 1.0  # 两侧都空 → 一致(但会被 min_rows 过滤掉)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _jaccard_multiset(a: Iterable, b: Iterable) -> float:
    ca = Counter(a)
    cb = Counter(b)
    if not ca and not cb:
        return 1.0
    if not ca or not cb:
        return 0.0
    # Counter 交集 / 并集(按 min/max 频次)
    inter = sum((ca & cb).values())
    union = sum((ca | cb).values())
    return inter / union if union else 0.0


def _non_empty_row_count(rows: list[list[Any]]) -> int:
    return sum(1 for r in rows if any(_cell_nonempty(c) for c in r))


def _compute_sheet_pair(
    sheet_a: SheetInput,
    sheet_b: SheetInput,
    sub_weights: tuple[float, float, float],
) -> SheetFieldResult:
    header_a = _extract_header_tokens(sheet_a.rows)
    header_b = _extract_header_tokens(sheet_b.rows)
    header_sim = _jaccard_set(header_a, header_b)

    bits_a = [
        _row_bitmask(r)
        for r in sheet_a.rows
        if any(_cell_nonempty(c) for c in r)
    ]
    bits_b = [
        _row_bitmask(r)
        for r in sheet_b.rows
        if any(_cell_nonempty(c) for c in r)
    ]
    bitmask_sim = _jaccard_multiset(bits_a, bits_b)

    merged_sim = _jaccard_set(sheet_a.merged_cells, sheet_b.merged_cells)

    wh, wb, wm = sub_weights
    total_w = wh + wb + wm
    if total_w <= 0:
        sub_score = 0.0
    else:
        sub_score = (
            header_sim * wh + bitmask_sim * wb + merged_sim * wm
        ) / total_w
    return SheetFieldResult(
        sheet_name=sheet_a.sheet_name,
        header_sim=round(header_sim, 4),
        bitmask_sim=round(bitmask_sim, 4),
        merged_cells_sim=round(merged_sim, 4),
        sub_score=round(sub_score, 4),
    )


def compute_field_similarity(
    sheets_a: list[SheetInput],
    sheets_b: list[SheetInput],
) -> FieldSimResult | None:
    """xlsx 字段结构相似度。

    按 sheet_name 配对,未配对 sheet 不贡献分数;
    配对后每 sheet 子评分 = header/bitmask/merged 加权;
    整体 score = max(per_sheet.sub_score)。

    任一方 sheets 为空 或 全 sheet 非空行数 < MIN_SHEET_ROWS → None(维度 skip)。
    """
    min_rows = config.min_sheet_rows()

    def _valid(sheets: list[SheetInput]) -> list[SheetInput]:
        return [s for s in sheets if _non_empty_row_count(s.rows) >= min_rows]

    va = _valid(sheets_a)
    vb = _valid(sheets_b)
    if not va or not vb:
        return None

    # 按 sheet_name 配对
    by_name_b = {s.sheet_name: s for s in vb}
    pairs: list[tuple[SheetInput, SheetInput]] = []
    for s_a in va:
        s_b = by_name_b.get(s_a.sheet_name)
        if s_b is not None:
            pairs.append((s_a, s_b))

    if not pairs:
        return None  # 没有同名 sheet,维度不可计算

    sub_weights = config.field_sub_weights()
    per_sheet = [_compute_sheet_pair(a, b, sub_weights) for a, b in pairs]
    # 按 sub_score 降序,上限 5
    per_sheet.sort(key=lambda x: x.sub_score, reverse=True)
    top = per_sheet[:5]
    total = max(s.sub_score for s in per_sheet) if per_sheet else 0.0
    return FieldSimResult(score=round(total, 4), per_sheet=top)
