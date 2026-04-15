"""error_consistency 关键词抽取 (C13)

正常模式:从 bidder.identity_info JSONB 抽 4 类字段值平铺。
降级模式:仅返 [bidder.name](贴 spec §F-DA-02 "用投标人名称做关键词交叉搜索")。

字段命名兼容 C5 LLM 提取的 schema 与 spec §L-1 (公司全称/简称/关键人员/资质编号/联系方式)。
"""

from __future__ import annotations

import unicodedata
from typing import Any

from app.models.bidder import Bidder
from app.services.detect.agents.error_impl.config import ErrorConsistencyConfig


# C5 LLM 提取的 identity_info 字段名(贴 spec §L-1 输出结构)
_FIELD_KEYS = (
    "company_name",   # 公司全称
    "short_name",     # 简称(可为 list)
    "key_persons",    # 关键人员姓名(list)
    "credentials",    # 资质编号(list)
)


def _to_strings(val: Any) -> list[str]:
    """把任意值 (str / list / None) 归一化为字符串列表(过滤空)。"""
    if val is None:
        return []
    if isinstance(val, str):
        s = val.strip()
        return [s] if s else []
    if isinstance(val, list):
        out: list[str] = []
        for item in val:
            if isinstance(item, str):
                s = item.strip()
                if s:
                    out.append(s)
            elif item is not None:
                s = str(item).strip()
                if s:
                    out.append(s)
        return out
    # dict / int / etc 一律 str 化
    s = str(val).strip()
    return [s] if s else []


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def extract_keywords(
    bidder: Bidder, cfg: ErrorConsistencyConfig, *, downgrade: bool = False
) -> list[str]:
    """抽取 bidder 关键词集合。

    - downgrade=True → 仅 [bidder.name](过滤短词)
    - downgrade=False → identity_info 4 类字段平铺(过滤短词、NFKC 归一、去重保序)
    """
    raw: list[str] = []
    if downgrade:
        if bidder.name:
            raw.append(bidder.name)
    else:
        info = bidder.identity_info
        if isinstance(info, dict):
            for key in _FIELD_KEYS:
                raw.extend(_to_strings(info.get(key)))

    # NFKC 归一 + 短词过滤 + 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for s in raw:
        ns = _nfkc(s)
        if len(ns) < cfg.min_keyword_len:
            continue
        if ns in seen:
            continue
        seen.add(ns)
        out.append(ns)
    return out


__all__ = ["extract_keywords"]
