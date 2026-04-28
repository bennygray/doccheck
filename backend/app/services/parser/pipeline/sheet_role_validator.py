"""Sheet 角色数值一致性校验 (fix-multi-sheet-price-double-count F).

LLM 给的 sheet_role 是概率性分类,可能误判。本模块用 deterministic 数值关系校验:
- 计算每 sheet 的 raw SUM
- 若两 sheet 的 SUM 在 1% 容差内相等 → 标"潜在重复表达"
- 若 LLM 已分清(main+breakdown)→ 不动
- 若 LLM 都标 main 或都缺 → 行数少的为 main,多的为 breakdown(主表特征:行少、值大)

纯函数:不直接写 DB,返修正后的 sheets_config 副本。调用方负责持久化。
"""

from __future__ import annotations

import copy
import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

# 两 sheet SUM 容差(1%);相对误差 |a-b| / max(a,b) ≤ EPSILON 视为相等
SUM_EQUAL_EPSILON: float = 0.01


def compute_sheet_sums(
    price_items: list[Any],
) -> dict[str, Decimal]:
    """按 sheet_name group sum(total_price)。

    Args:
        price_items: PriceItem 实例列表(或 dict-like 含 sheet_name + total_price)

    Returns:
        dict[sheet_name, sum_total]:NULL total_price 忽略;sum=0 的 sheet 也保留(下游过滤)
    """
    sums: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for pi in price_items:
        sn = _get(pi, "sheet_name")
        tp = _get(pi, "total_price")
        if sn is None or tp is None:
            continue
        try:
            sums[sn] += Decimal(str(tp))
        except (TypeError, ValueError):
            continue
    return dict(sums)


def compute_sheet_row_counts(price_items: list[Any]) -> dict[str, int]:
    """按 sheet_name group 行数(已过滤后入库的 price_items 行数)。"""
    counts: dict[str, int] = defaultdict(int)
    for pi in price_items:
        sn = _get(pi, "sheet_name")
        if sn is None:
            continue
        counts[sn] += 1
    return dict(counts)


def find_suspect_pairs(
    sheet_sums: dict[str, Decimal],
    epsilon: float = SUM_EQUAL_EPSILON,
) -> list[tuple[str, str]]:
    """找所有"潜在重复表达"对(SUM 相对误差 ≤ epsilon 的两 sheet)。

    skip SUM=0 的 sheet(可能整 sheet 数据缺失)。
    返回 (sheet_a, sheet_b) 列表,字典序稳定(便于测试).
    """
    pairs: list[tuple[str, str]] = []
    names = sorted(sheet_sums.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            sum_a, sum_b = sheet_sums[a], sheet_sums[b]
            if sum_a == 0 or sum_b == 0:
                continue
            denom = max(abs(sum_a), abs(sum_b))
            if denom == 0:
                continue
            ratio = abs(sum_a - sum_b) / denom
            if ratio <= Decimal(str(epsilon)):
                pairs.append((a, b))
    return pairs


def validate_sheet_roles(
    sheets_config: list[dict[str, Any]],
    price_items: list[Any],
    epsilon: float = SUM_EQUAL_EPSILON,
) -> tuple[list[dict[str, Any]], list[str]]:
    """对 sheets_config 做数值兜底校验,返修正后的副本 + 修正日志。

    算法:
    1. 算每 sheet 的 SUM 与行数
    2. 找 SUM 相等的 (a, b) 对
    3. 对每对:
       - LLM 已分清(main+breakdown / main+summary)→ 不动
       - LLM 都 main 或都缺 → 行数少的为 main,多的为 breakdown
       - 行数相等(罕见)→ 保留 LLM 第一个为 main + log warning

    Args:
        sheets_config: LLM 输出的 sheets_config(每项含 sheet_name + sheet_role 等)
        price_items: 已入库的 PriceItem(用于算 SUM 和行数)
        epsilon: SUM 相等容差

    Returns:
        (修正后的 sheets_config 副本, 修正决策日志列表)
    """
    if not sheets_config or len(sheets_config) < 2:
        return list(sheets_config), []

    sheet_sums = compute_sheet_sums(price_items)
    row_counts = compute_sheet_row_counts(price_items)
    suspect_pairs = find_suspect_pairs(sheet_sums, epsilon)

    if not suspect_pairs:
        return list(sheets_config), []

    # 副本以避免原地修改
    fixed = copy.deepcopy(sheets_config)
    by_name: dict[str, dict[str, Any]] = {item["sheet_name"]: item for item in fixed}
    decisions: list[str] = []

    for a, b in suspect_pairs:
        item_a = by_name.get(a)
        item_b = by_name.get(b)
        if item_a is None or item_b is None:
            continue
        role_a = item_a.get("sheet_role", "main")
        role_b = item_b.get("sheet_role", "main")

        # LLM 已正确分清:一个 main 一个 breakdown/summary → 不动
        if role_a == "main" and role_b in {"breakdown", "summary"}:
            continue
        if role_b == "main" and role_a in {"breakdown", "summary"}:
            continue

        # 都 main 或都不 main → 兜底
        rows_a = row_counts.get(a, 0)
        rows_b = row_counts.get(b, 0)
        sum_a = sheet_sums.get(a, Decimal(0))
        sum_b = sheet_sums.get(b, Decimal(0))

        if rows_a < rows_b:
            item_a["sheet_role"] = "main"
            item_b["sheet_role"] = "breakdown"
            msg = (
                f"sheet_role validator fix: {a}({rows_a} rows, sum={sum_a}) → main; "
                f"{b}({rows_b} rows, sum={sum_b}) → breakdown"
            )
        elif rows_a > rows_b:
            item_a["sheet_role"] = "breakdown"
            item_b["sheet_role"] = "main"
            msg = (
                f"sheet_role validator fix: {b}({rows_b} rows, sum={sum_b}) → main; "
                f"{a}({rows_a} rows, sum={sum_a}) → breakdown"
            )
        else:
            # 行数相等 + SUM 相等(罕见)→ 保留 LLM 输出的第一个为 main
            # stable order:按字典序第一个为 main
            item_a["sheet_role"] = "main"
            item_b["sheet_role"] = "breakdown"
            msg = (
                f"sheet_role validator fix (rare equal-rows): "
                f"{a}={rows_a} rows / {b}={rows_b} rows, sum equal; "
                f"defaulting {a} → main, {b} → breakdown (manual review needed)"
            )
        logger.warning(msg)
        decisions.append(msg)

    return fixed, decisions


def _get(obj: Any, attr: str) -> Any:
    """从 ORM 实例 / dict 取字段,容错。"""
    if isinstance(obj, dict):
        return obj.get(attr)
    return getattr(obj, attr, None)


__all__ = [
    "SUM_EQUAL_EPSILON",
    "compute_sheet_sums",
    "compute_sheet_row_counts",
    "find_suspect_pairs",
    "validate_sheet_roles",
]
