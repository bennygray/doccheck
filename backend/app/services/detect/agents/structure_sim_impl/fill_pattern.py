"""C9 表单填充模式维度:xlsx cell 类型 pattern Jaccard。

cell 归 4 类:N(数字)/ D(日期)/ T(文本)/ _(空);
每行 pattern 串接字符串(如 "TN_N_D"),两侧作为 multiset 算 Jaccard;
按 sheet_name 配对,整体 score = max(per_sheet.score)。
"""

from __future__ import annotations

import datetime as _dt
import re
from collections import Counter
from typing import Any

from app.services.detect.agents.structure_sim_impl import config
from app.services.detect.agents.structure_sim_impl.field_sig import (
    SheetInput,
    _non_empty_row_count,
)
from app.services.detect.agents.structure_sim_impl.models import (
    FillSimResult,
    SheetFillResult,
)

# ISO / 常见日期字符串探测
_DATE_PATTERNS = [
    re.compile(r"^\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}$"),
    re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日?$"),
]

# 数字字符串探测(允许整数/小数/负号/千分位)
_NUMBER_PATTERN = re.compile(r"^-?\d{1,3}(,\d{3})*(\.\d+)?$|^-?\d+(\.\d+)?$")


def _looks_like_date(s: str) -> bool:
    return any(p.match(s) for p in _DATE_PATTERNS)


def _looks_like_number(s: str) -> bool:
    return bool(_NUMBER_PATTERN.match(s))


def cell_type_pattern(cell: Any) -> str:
    """归类为 N / D / T / _。

    None / 空白 → '_';bool/int/float → 'N';datetime → 'D';
    str 尝试数字探测 → 'N',日期探测 → 'D',其他 → 'T'。
    """
    if cell is None:
        return "_"
    if isinstance(cell, bool):
        # bool 归为文本(而非数字)—— True/False 通常是配置开关,不是数值
        return "T"
    if isinstance(cell, (int, float)):
        return "N"
    if isinstance(cell, (_dt.datetime, _dt.date)):
        return "D"
    if isinstance(cell, str):
        s = cell.strip()
        if not s:
            return "_"
        if _looks_like_number(s):
            return "N"
        if _looks_like_date(s):
            return "D"
        return "T"
    return "T"  # 其他未知类型降级文本


def _row_pattern(row: list[Any]) -> str:
    return "".join(cell_type_pattern(c) for c in row)


def _compute_sheet_pair(
    sheet_a: SheetInput, sheet_b: SheetInput
) -> SheetFillResult:
    lines_a = [_row_pattern(r) for r in sheet_a.rows]
    lines_b = [_row_pattern(r) for r in sheet_b.rows]
    ca = Counter(lines_a)
    cb = Counter(lines_b)
    if not ca and not cb:
        score = 1.0
    elif not ca or not cb:
        score = 0.0
    else:
        inter = sum((ca & cb).values())
        union = sum((ca | cb).values())
        score = inter / union if union else 0.0
    # 前 10 条"共享频次较高"的 pattern 作为 sample(全 '_' 全空 pattern 无意义,过滤)
    shared = (ca & cb)
    interesting = [
        (p, n)
        for p, n in shared.items()
        if p and set(p) != {"_"}  # 非全空
    ]
    interesting.sort(key=lambda x: x[1], reverse=True)
    samples = [p for p, _ in interesting[:10]]
    return SheetFillResult(
        sheet_name=sheet_a.sheet_name,
        score=round(score, 4),
        matched_pattern_lines=sum((ca & cb).values()),
        sample_patterns=samples,
    )


def compute_fill_similarity(
    sheets_a: list[SheetInput],
    sheets_b: list[SheetInput],
) -> FillSimResult | None:
    """表单填充模式相似度。

    sheet 配对策略同 field_sig;任一方 sheets 为空
    或 全 sheet 非空行数 < MIN_SHEET_ROWS → None。
    """
    min_rows = config.min_sheet_rows()

    def _valid(sheets: list[SheetInput]) -> list[SheetInput]:
        return [s for s in sheets if _non_empty_row_count(s.rows) >= min_rows]

    va = _valid(sheets_a)
    vb = _valid(sheets_b)
    if not va or not vb:
        return None

    by_name_b = {s.sheet_name: s for s in vb}
    pairs: list[tuple[SheetInput, SheetInput]] = []
    for s_a in va:
        s_b = by_name_b.get(s_a.sheet_name)
        if s_b is not None:
            pairs.append((s_a, s_b))
    if not pairs:
        return None

    per_sheet = [_compute_sheet_pair(a, b) for a, b in pairs]
    per_sheet.sort(key=lambda x: x.score, reverse=True)
    top = per_sheet[:5]
    total = max(s.score for s in per_sheet) if per_sheet else 0.0
    return FillSimResult(score=round(total, 4), per_sheet=top)
