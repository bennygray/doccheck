"""章节切分 - 纯正则 5 PATTERN (C8 design D1)

5 种 PATTERN 按优先级匹配,命中即视为章节标题行:
1. 第 X 章        e.g. "第一章 投标函" / "第 3 章 技术方案"
2. 第 X 节        e.g. "第二节 工期保证"
3. X.Y 数字序号   e.g. "3.1 技术措施" / "1 技术方案"(一级数字)
4. 中文数字+顿号  e.g. "一、投标函" / "二、商务标"
5. 纯数字+顿号    e.g. "1. 投标函" / "1、投标函"

短章节合并:章节内文本 < min_chapter_chars 合并进前一章节,避免孤立标题行后
被下一次命中截断产生的碎章节。
"""

from __future__ import annotations

import re

from app.services.detect.agents.section_sim_impl.models import ChapterBlock

# 5 种 PATTERN(按优先级)
_PATTERNS: list[re.Pattern] = [
    # 1. 第 X 章
    re.compile(r"^\s*第\s*[一二三四五六七八九十百千零〇\d]+\s*章[\s\.、:]"),
    # 2. 第 X 节
    re.compile(r"^\s*第\s*[一二三四五六七八九十百千零〇\d]+\s*节[\s\.、:]"),
    # 3. X.Y 数字序号(要求至少一个点,如 "3.1" 或 "3.1.2";纯 "1" 放到 #5)
    re.compile(r"^\s*\d+(\.\d+)+\s+\S"),
    # 4. 中文数字 + 顿号
    re.compile(r"^\s*[一二三四五六七八九十]+\s*[、\.]\s*\S"),
    # 5. 纯数字 + 顿号 / 空格(如 "1. 投标函" / "1、" / "1 投标函")
    re.compile(r"^\s*\d+\s*[、\.]\s*\S|^\s*\d+\s{1,3}[^\d\s]"),
]

# 标题长度上限(截断防爆)
_TITLE_MAX_CHARS = 100


def _is_chapter_title(line: str) -> bool:
    """line 是否为章节标题行(匹配任一 PATTERN)。"""
    return any(pat.match(line) for pat in _PATTERNS)


def extract_chapters(
    paragraphs: list[str], min_chapter_chars: int
) -> list[ChapterBlock]:
    """按正则识别标题行,切出 ChapterBlock 列表。

    边界:
    - 空输入 → 返 []
    - 无任何命中 → 返 [](全文走降级)
    - 标题行后无正文 → 该章节 paragraphs=[] total_chars=0(会被短章节合并吸收)
    """
    if not paragraphs:
        return []

    raw_chapters: list[dict] = []
    current: dict | None = None
    for para in paragraphs:
        if not para or not para.strip():
            continue
        if _is_chapter_title(para):
            # flush 前一章节
            if current is not None:
                raw_chapters.append(current)
            current = {
                "title": para.strip()[:_TITLE_MAX_CHARS],
                "paragraphs": [],
            }
        else:
            if current is None:
                # 首次命中前的段落:忽略(无归属章节);
                # 常见投标文档开头是"标书封面 / 目录"等散段,无需纳入
                continue
            current["paragraphs"].append(para.strip())
    if current is not None:
        raw_chapters.append(current)

    if not raw_chapters:
        return []

    # 合并短章节:章节内文本 < min_chapter_chars,合并进前一章节
    merged: list[dict] = []
    for ch in raw_chapters:
        total = sum(len(p) for p in ch["paragraphs"])
        if total < min_chapter_chars and merged:
            # 合并:把当前章节的 title 作为一段归入前一章节(保留章节边界感),
            # 再把 paragraphs 追加
            merged[-1]["paragraphs"].append(ch["title"])
            merged[-1]["paragraphs"].extend(ch["paragraphs"])
        else:
            merged.append(ch)

    # 构造 ChapterBlock(idx 按 merged 顺序重新编号)
    result: list[ChapterBlock] = []
    for i, ch in enumerate(merged):
        total = sum(len(p) for p in ch["paragraphs"])
        result.append(
            ChapterBlock(
                idx=i,
                title=ch["title"],
                paragraphs=tuple(ch["paragraphs"]),
                total_chars=total,
            )
        )
    return result


__all__ = ["extract_chapters"]
