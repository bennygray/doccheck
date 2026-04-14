"""字段归一化 (C10 detect-agents-metadata)

规则:NFKC(全角→半角)+ casefold(大小写)+ strip(空白)。
空串视同 None;纯空白亦视同 None。
"""

from __future__ import annotations

import unicodedata


def nfkc_casefold_strip(s: str | None) -> str | None:
    """对字符串做 NFKC + casefold + strip,空串/None 返 None。"""
    if s is None:
        return None
    t = unicodedata.normalize("NFKC", s).casefold().strip()
    return t or None


__all__ = ["nfkc_casefold_strip"]
