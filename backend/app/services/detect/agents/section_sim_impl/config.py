"""section_similarity Agent 运行期配置 (C8)

- SECTION_SIM_MIN_CHAPTERS          默认 3     任一侧章节数 < 此值触发降级
- SECTION_SIM_MIN_CHAPTER_CHARS     默认 100   章节内字符 < 此值合并进前一章节
- SECTION_SIM_TITLE_ALIGN_THRESHOLD 默认 0.40  title TF-IDF sim ≥ 此值算对齐成功

复用 C7 env(通过 import text_sim_impl.config):
- TEXT_SIM_MIN_DOC_CHARS        文档总字数下限(preflight)
- TEXT_SIM_PAIR_SCORE_THRESHOLD 段落对 sim 阈值
- TEXT_SIM_MAX_PAIRS_TO_LLM     LLM 上限(章节跨对合并后共享)
"""

from __future__ import annotations

import os


def min_chapters() -> int:
    try:
        return int(os.environ.get("SECTION_SIM_MIN_CHAPTERS", "3"))
    except ValueError:
        return 3


def min_chapter_chars() -> int:
    try:
        return int(os.environ.get("SECTION_SIM_MIN_CHAPTER_CHARS", "100"))
    except ValueError:
        return 100


def title_align_threshold() -> float:
    try:
        return float(os.environ.get("SECTION_SIM_TITLE_ALIGN_THRESHOLD", "0.40"))
    except ValueError:
        return 0.40


__all__ = ["min_chapters", "min_chapter_chars", "title_align_threshold"]
