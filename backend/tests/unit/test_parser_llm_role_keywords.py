"""L1 - parser/llm/role_keywords 兜底规则 (C5 §9.4)"""

from __future__ import annotations

import pytest

from app.services.parser.llm.role_keywords import (
    ROLE_KEYWORDS,
    classify_by_keywords,
)


def test_role_keywords_has_8_roles() -> None:
    # 9 种角色中 8 个有关键词,other 是默认兜底
    assert set(ROLE_KEYWORDS.keys()) == {
        "pricing",
        "unit_price",
        "technical",
        "construction",
        "bid_letter",
        "qualification",
        "company_intro",
        "authorization",
    }
    for kws in ROLE_KEYWORDS.values():
        assert isinstance(kws, list) and len(kws) > 0


@pytest.mark.parametrize(
    "file_name,expected",
    [
        ("投标报价.xlsx", "pricing"),
        ("工程量清单.xlsx", "pricing"),
        ("技术方案.docx", "technical"),
        ("技术建议书.docx", "technical"),
        ("施工组织设计.docx", "construction"),
        ("综合单价分析表.xlsx", "unit_price"),
        ("投标函.docx", "bid_letter"),
        ("资质证明.pdf", "qualification"),
        ("营业执照.jpg", "qualification"),
        ("企业介绍.docx", "company_intro"),
        ("授权委托书.docx", "authorization"),
        ("XYZ.docx", "other"),
        ("无关.docx", "other"),
    ],
)
def test_classify_by_keywords(file_name: str, expected: str) -> None:
    assert classify_by_keywords(file_name) == expected


def test_case_insensitive_match() -> None:
    # 英文关键词比例低,主要针对中文,但 lower() 不影响
    assert classify_by_keywords("投标报价.XLSX") == "pricing"
