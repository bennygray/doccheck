"""section_similarity 纯数据类型 (C8)

dataclass 全部可 pickle 进 ProcessPoolExecutor 子进程。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ChapterBlock:
    """一个章节:标题 + 内部段落。

    - idx         : 章节序号(0-based,章节切分后的次序)
    - title       : 章节标题原文(包含数字序号,截 100 字)
    - paragraphs  : 章节内段落列表(不含标题行本身)
    - total_chars : 所有段落字符总和
    """

    idx: int
    title: str
    paragraphs: tuple[str, ...]  # tuple 保证不可变/可 hash
    total_chars: int


@dataclass(frozen=True)
class ChapterPair:
    """章节对齐结果。"""

    a_idx: int
    b_idx: int
    title_sim: float  # 0~1
    aligned_by: Literal["title", "index"]


@dataclass
class ChapterScoreResult:
    """单个对齐章节对的评分结果。"""

    chapter_pair_idx: int  # 在 chapter_pairs 列表中的下标
    a_idx: int
    b_idx: int
    a_title: str
    b_title: str
    title_sim: float
    aligned_by: Literal["title", "index"]
    chapter_score: float  # 0~100
    is_chapter_ironclad: bool
    plagiarism_count: int
    para_pair_count: int  # 章节内段落对数(sim >= threshold)
    samples: list[dict] = field(default_factory=list)  # 前 5 条 para 对(本章节内)


__all__ = ["ChapterBlock", "ChapterPair", "ChapterScoreResult"]
