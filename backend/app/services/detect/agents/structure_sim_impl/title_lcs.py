"""C9 目录结构维度:docx 章节标题 LCS 相似度。

复用 C8 `section_sim_impl.chapter_parser.extract_chapters` 切章,
取 `ChapterBlock.title` 做归一化后 LCS。
"""

from __future__ import annotations

import logging
import re

from app.services.detect.agents.structure_sim_impl import config
from app.services.detect.agents.structure_sim_impl.models import DirResult

logger = logging.getLogger(__name__)

# 章节序号前缀规则(按最长优先匹配);剥离后保留标题实质内容
_PATTERNS_PREFIX = [
    re.compile(r"^\s*第\s*[一二三四五六七八九十百千\d]+\s*章\s*"),
    re.compile(r"^\s*第\s*[一二三四五六七八九十百千\d]+\s*节\s*"),
    re.compile(r"^\s*\d+(?:\.\d+)*\s+"),
    re.compile(r"^\s*[一二三四五六七八九十]+\s*[、\.]\s*"),
    re.compile(r"^\s*\d+\s*[、\.]\s*"),
]

# 标点归一化(全角 → 半角,去空白/顿号/标点)
_PUNCT_STRIP = re.compile(r"[\s\u3000、,,。.\-—_/()()【】\[\]:：;;!?!?\"“”'‘’]+")


def _normalize_title(title: str) -> str:
    """剥离序号前缀 + 去空白全角 + 统一标点 → 归一化后的标题实质内容。"""
    if not title:
        return ""
    s = title.strip()
    for pat in _PATTERNS_PREFIX:
        m = pat.match(s)
        if m:
            s = s[m.end():]
            break
    # 去所有空白和常见标点
    s = _PUNCT_STRIP.sub("", s)
    return s


def _lcs_length(a: list[str], b: list[str]) -> int:
    """经典 LCS DP,O(m×n)。两边都较小(< 100 章节),无性能问题。"""
    if not a or not b:
        return 0
    m, n = len(a), len(b)
    # 一维数组优化
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        ai = a[i - 1]
        for j in range(1, n + 1):
            if ai == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev = curr
    return prev[n]


def _lcs_matched_titles(
    norm_a: list[str], norm_b: list[str], orig_a: list[str], limit: int = 10
) -> list[str]:
    """回溯 LCS 取匹配到的标题列表(用归一化后相等,返回 orig_a 的原文)。"""
    if not norm_a or not norm_b:
        return []
    m, n = len(norm_a), len(norm_b)
    # 完整 DP 表做回溯(规模小,接受 O(m*n) 空间)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if norm_a[i - 1] == norm_b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    matched: list[str] = []
    i, j = m, n
    while i > 0 and j > 0 and len(matched) < limit:
        if norm_a[i - 1] == norm_b[j - 1]:
            matched.append(orig_a[i - 1])
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    return list(reversed(matched))


def _compute_sync(
    titles_a: list[str],
    titles_b: list[str],
) -> tuple[int, list[str]]:
    norm_a = [_normalize_title(t) for t in titles_a]
    norm_b = [_normalize_title(t) for t in titles_b]
    # 过滤空归一化(只序号无实质内容的 title)
    paired_a = [(n, o) for n, o in zip(norm_a, titles_a, strict=True) if n]
    paired_b = [(n, o) for n, o in zip(norm_b, titles_b, strict=True) if n]
    if not paired_a or not paired_b:
        return 0, []
    na = [p[0] for p in paired_a]
    nb = [p[0] for p in paired_b]
    oa = [p[1] for p in paired_a]
    lcs_len = _lcs_length(na, nb)
    matched = _lcs_matched_titles(na, nb, oa, limit=10)
    return lcs_len, matched


async def compute_directory_similarity(
    titles_a: list[str],
    titles_b: list[str],
    doc_id_a: int | None = None,
    doc_id_b: int | None = None,
) -> DirResult | None:
    """LCS-based 目录相似度 → DirResult,章节数不足返 None。

    章节数下限 = `STRUCTURE_SIM_MIN_CHAPTERS`(默认 3)。
    CPU 密集走 ProcessPoolExecutor(复用 C7/C8 通道)。
    """
    min_n = config.min_chapters()
    if len(titles_a) < min_n or len(titles_b) < min_n:
        return None

    # harden-async-infra F1:per-task 子进程隔离
    from app.core.config import settings
    from app.services.detect.agents._subprocess import run_isolated

    lcs_len, matched = await run_isolated(
        _compute_sync,
        titles_a,
        titles_b,
        timeout=settings.agent_subprocess_timeout,
    )
    total = len(titles_a) + len(titles_b)
    score = (2 * lcs_len / total) if total > 0 else 0.0
    score = max(0.0, min(1.0, score))
    return DirResult(
        score=round(score, 4),
        titles_a_count=len(titles_a),
        titles_b_count=len(titles_b),
        lcs_length=lcs_len,
        sample_titles_matched=matched,
        doc_id_a=doc_id_a,
        doc_id_b=doc_id_b,
    )
