"""字段归一化 + Decimal 拆解 (C11 price_impl)

3 个纯函数:
- normalize_item_name(s):NFKC + casefold + strip;空串/None → None(对齐 C10)
- split_price_tail(total, tail_n):返 (尾 N 位字符串, 整数位长);异常样本 → None
- decimal_to_float_safe(d):Decimal → float;失败 → None(供 series 子检测)
"""

from __future__ import annotations

import unicodedata
from decimal import Decimal, InvalidOperation


def normalize_item_name(name: str | None) -> str | None:
    """对 item_name 做 NFKC + casefold + strip,空串/None 返 None。"""
    if name is None:
        return None
    t = unicodedata.normalize("NFKC", name).casefold().strip()
    return t or None


def split_price_tail(
    total_price: Decimal | None, tail_n: int
) -> tuple[str, int] | None:
    """返 (尾 N 位字符串, 整数位长);异常样本 → None。

    Decimal → int 用 truncate(int(Decimal('1000.99')) == 1000)。
    负值 / NaN / 异常 → None。
    整数位长 < tail_n 时 zfill 前补 0,避免 tail 长度小于 tail_n。
    """
    if total_price is None:
        return None
    try:
        int_val = int(total_price)
    except (InvalidOperation, ValueError, TypeError):
        return None
    if int_val < 0:
        return None
    int_str = str(int_val)
    int_len = len(int_str)
    if int_len >= tail_n:
        tail = int_str[-tail_n:]
    else:
        tail = int_str.zfill(tail_n)
    return (tail, int_len)


def decimal_to_float_safe(d: Decimal | None) -> float | None:
    """Decimal → float;None 透传;异常 → None。"""
    if d is None:
        return None
    try:
        return float(d)
    except (InvalidOperation, ValueError, TypeError):
        return None


__all__ = [
    "normalize_item_name",
    "split_price_tail",
    "decimal_to_float_safe",
]
