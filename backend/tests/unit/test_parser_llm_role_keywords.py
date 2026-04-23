"""L1 - parser/llm/role_keywords 兜底规则 (C5 §9.4)"""

from __future__ import annotations

import pytest

from app.services.parser.llm.role_keywords import (
    ROLE_KEYWORDS,
    classify_by_keywords,
    classify_by_keywords_on_text,
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
    ],
)
def test_classify_by_keywords_hit(file_name: str, expected: str) -> None:
    assert classify_by_keywords(file_name) == expected


@pytest.mark.parametrize(
    "file_name",
    ["XYZ.docx", "无关.docx", "", "random-file.pdf"],
)
def test_classify_by_keywords_miss_returns_none(file_name: str) -> None:
    # fix-mac-packed-zip-parsing 契约变更:未命中返回 None(原为 "other")
    assert classify_by_keywords(file_name) is None


def test_case_insensitive_match() -> None:
    # 英文关键词比例低,主要针对中文,但 lower() 不影响
    assert classify_by_keywords("投标报价.XLSX") == "pricing"


# ---- classify_by_keywords_on_text (新增正文兜底) ----


@pytest.mark.parametrize(
    "text,expected",
    [
        ("本公司针对本次招标项目提交投标报价一览表如下", "pricing"),
        ("技术方案概述如下", "technical"),
        ("施工组织设计总说明", "construction"),
        ("投标函致某某招标人", "bid_letter"),
        ("营业执照复印件", "qualification"),
        ("公司简介", "company_intro"),
        ("法定代表人授权委托书", "authorization"),
        ("综合单价分析按国标", "unit_price"),
    ],
)
def test_classify_by_keywords_on_text_hit(text: str, expected: str) -> None:
    assert classify_by_keywords_on_text(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "完全无关的随机文本", "lorem ipsum dolor sit amet"],
)
def test_classify_by_keywords_on_text_miss_returns_none(text: str) -> None:
    assert classify_by_keywords_on_text(text) is None


# ---- honest-detection-results N2: 10 个新增行业术语命中 ----


@pytest.mark.parametrize(
    "file_name,expected",
    [
        ("XX 价格标.docx", "pricing"),
        ("开标一览表.xlsx", "pricing"),
        ("XX 资信标.docx", "qualification"),
        ("资信证明.pdf", "qualification"),
        ("类似业绩汇总.docx", "qualification"),
        ("业绩证明.pdf", "qualification"),
        ("企业简介.docx", "company_intro"),
        ("施工进度计划.docx", "construction"),
        ("进度计划表.xlsx", "construction"),
    ],
)
def test_new_industry_keywords_hit(file_name: str, expected: str) -> None:
    assert classify_by_keywords(file_name) == expected


def test_new_keyword_via_content() -> None:
    # 正文里出现"类似业绩"也应命中 qualification
    assert (
        classify_by_keywords_on_text("本公司近三年完成如下类似业绩:xxx")
        == "qualification"
    )
