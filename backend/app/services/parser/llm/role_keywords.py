"""角色关键词兜底规则 (C5 parser-pipeline - D2 决策;
fix-mac-packed-zip-parsing 3.1 扩展为两级兜底)。

LLM 角色分类失败时,两级兜底链路:
1. `classify_by_keywords_on_text(first_paragraph)` — 正文首段关键词匹配
2. `classify_by_keywords(file_name)` — 文件名关键词匹配(历史行为)

任一函数未命中时返回 ``None``(调用方据此决定进入下一层或兜底到 ``"other"``)。
按字典声明顺序遍历 ``ROLE_KEYWORDS``,首次命中即返回对应角色。
"""

from __future__ import annotations

# 9 种角色中 8 个有关键词,other 为默认兜底
ROLE_KEYWORDS: dict[str, list[str]] = {
    "pricing": ["投标报价", "报价清单", "工程量清单", "报价", "清单", "商务标"],
    "unit_price": ["综合单价", "单价分析"],
    "technical": ["技术方案", "技术标", "技术建议书"],
    "construction": ["施工组织", "施工方案", "施工设计"],
    "bid_letter": ["投标函", "投标书"],
    "qualification": ["资质证明", "资格", "营业执照", "资质"],
    "company_intro": ["企业介绍", "公司简介", "公司概况"],
    "authorization": ["授权委托书", "授权", "委托"],
}


def _match_keyword(haystack: str) -> str | None:
    """对 haystack 做子串包含匹配(不区分大小写),首次命中即返回 role。

    字典迭代顺序按声明序(Python 3.7+ 保证)。
    """
    if not haystack:
        return None
    lowered = haystack.lower()
    for role, kws in ROLE_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in lowered:
                return role
    return None


def classify_by_keywords(file_name: str) -> str | None:
    """按文件名做关键词匹配。未命中返回 ``None``(调用方决定兜底为 "other")。

    **行为变更**(fix-mac-packed-zip-parsing):此前未命中返回 ``"other"``,现改为
    ``None``,以便上层区分"命中 other(目前不存在)"和"未命中"。现存调用点
    (``role_classifier._apply_keyword_fallback``)必须自行把 ``None`` 兜底为
    ``"other"``。
    """
    return _match_keyword(file_name or "")


def classify_by_keywords_on_text(text: str) -> str | None:
    """按正文首段(已截断)做关键词匹配。未命中返回 ``None``。

    调用者负责传入已经截断到 ≤1000 字的首段文本;本函数只做匹配。
    """
    return _match_keyword(text or "")


__all__ = [
    "ROLE_KEYWORDS",
    "classify_by_keywords",
    "classify_by_keywords_on_text",
]
