"""L1 - chapter_parser 单元测试 (C8)"""

from __future__ import annotations

from app.services.detect.agents.section_sim_impl.chapter_parser import (
    _is_chapter_title,
    extract_chapters,
)

# ---------- _is_chapter_title: 5 种 PATTERN ----------

def test_pattern1_chinese_chapter():
    assert _is_chapter_title("第一章 投标函")
    assert _is_chapter_title("第 3 章 技术方案")
    assert _is_chapter_title("第十二章:商务标")


def test_pattern2_chinese_section():
    assert _is_chapter_title("第二节 工期保证")
    assert _is_chapter_title("第 5 节、施工组织")


def test_pattern3_dotted_number():
    assert _is_chapter_title("3.1 技术措施")
    assert _is_chapter_title("3.1.2 进度计划")


def test_pattern4_chinese_number_dun():
    assert _is_chapter_title("一、投标函")
    assert _is_chapter_title("二、商务标")
    assert _is_chapter_title("十、附录")


def test_pattern5_plain_number_dun():
    assert _is_chapter_title("1. 投标函")
    assert _is_chapter_title("1、投标函")
    assert _is_chapter_title("2 投标函")


def test_non_title_lines():
    assert not _is_chapter_title("本项目采用先进的技术方案")
    assert not _is_chapter_title("单纯数字 12345 不带标题")
    assert not _is_chapter_title("")
    assert not _is_chapter_title("第章 缺数字")


# ---------- extract_chapters: 组合 ----------

def test_extract_chapters_empty():
    assert extract_chapters([], 100) == []


def test_extract_chapters_no_title_match():
    """无任何命中 → 返 [](走降级)。"""
    paras = ["本项目采用先进技术方案", "团队经验丰富", "工期保证"]
    assert extract_chapters(paras, 100) == []


def test_extract_chapters_basic_three_chapters():
    paras = [
        "第一章 投标函",
        "本公司投标…" * 20,  # ~100 chars
        "保证实现所有要求…" * 20,
        "第二章 商务标",
        "含报价明细…" * 20,
        "综合单价 5000…" * 20,
        "第三章 技术标",
        "技术方案如下…" * 20,
        "施工进度保证…" * 20,
    ]
    chapters = extract_chapters(paras, 100)
    assert len(chapters) == 3
    assert chapters[0].title.startswith("第一章")
    assert chapters[1].title.startswith("第二章")
    assert chapters[2].title.startswith("第三章")
    for i, c in enumerate(chapters):
        assert c.idx == i
        assert c.total_chars >= 100


def test_extract_chapters_merge_short():
    """短章节(< 100 字)合并进前一章节。"""
    paras = [
        "第一章 投标函",
        "本公司投标…" * 30,  # 长章节
        "第二章 超短",
        "太短",  # < 100 字
        "第三章 后续",
        "后续内容…" * 30,
    ]
    chapters = extract_chapters(paras, 100)
    # 第二章被合并进第一章(因第二章内文本 < 100),剩 2 章节
    assert len(chapters) == 2
    assert chapters[0].title.startswith("第一章")
    assert chapters[1].title.startswith("第三章")
    # 第二章的 title "第二章 超短" 被合并进第一章 paragraphs
    first_chapter_text = "\n".join(chapters[0].paragraphs)
    assert "超短" in first_chapter_text


def test_extract_chapters_title_only_no_body():
    """标题行后无正文 → 该章节 paragraphs=[] total_chars=0 → 被合并进前一章节。"""
    paras = [
        "第一章 投标函",
        "本公司投标…" * 30,
        "第二章 无内容",
        "第三章 后续",
        "后续内容…" * 30,
    ]
    chapters = extract_chapters(paras, 100)
    # 第二章 total_chars=0 被合并
    assert len(chapters) == 2


def test_extract_chapters_leading_non_title_ignored():
    """首次章节标题前的段落(如封面/目录)忽略。"""
    paras = [
        "标书封面",  # 非标题,忽略
        "目录:一、二、三",  # 这个匹配 PATTERN4 "一、...",会被当章节;加前缀防
        "投标单位:XXX 公司(非标题)",
        "第一章 投标函",
        "本公司投标…" * 30,
    ]
    chapters = extract_chapters(paras, 100)
    # 因"目录:一、二、三" 不匹配 PATTERN4(line 开头不是"一、"),被忽略
    assert len(chapters) == 1
    assert chapters[0].title.startswith("第一章")


def test_extract_chapters_title_truncated():
    """title 超长截 100 字。"""
    long_title = "第一章 " + "长" * 200
    paras = [long_title, "正文" * 60]
    chapters = extract_chapters(paras, 100)
    assert len(chapters) == 1
    assert len(chapters[0].title) <= 100
