"""角色关键词兜底规则 (C5 parser-pipeline - D2 决策)

LLM 角色分类失败时,退化为文件名关键词匹配。
按字典声明顺序遍历,首次命中即返回对应角色;全未命中返 "other"。

D8 决策:本期 Python 常量,C17 升级为 DB + admin UI。
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


def classify_by_keywords(file_name: str) -> str:
    """按声明顺序遍历,首次命中即返回;全未命中 → 'other'。

    匹配策略:子串包含(不区分大小写,但中文是 case-insensitive no-op)。
    """
    name = file_name.lower()
    for role, kws in ROLE_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in name:
                return role
    return "other"


__all__ = ["ROLE_KEYWORDS", "classify_by_keywords"]
