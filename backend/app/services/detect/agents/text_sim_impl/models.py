"""text_similarity 纯数据类型 (C7 detect-agent-text-similarity)

ParaPair 需要可 pickle 进 ProcessPoolExecutor 子进程,故用 @dataclass
(不用 namedtuple 是因为要带字段语义清晰、便于 evidence 构造)。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParaPair:
    """一对超阈值段落对。

    a_idx / b_idx  : 在 segmenter 切出的段落列表中的下标
    a_text / b_text: 段落原文(最长 200 字,evidence 存入前已截断)
    sim            : cosine 相似度 ∈ [0, 1]
    """

    a_idx: int
    b_idx: int
    a_text: str
    b_text: str
    sim: float


__all__ = ["ParaPair"]
