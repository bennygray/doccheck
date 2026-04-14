"""text_similarity Agent 运行期配置 (动态读 env,测试 monkeypatch 友好)

3 个 env 均可在运行时调整:
- TEXT_SIM_MIN_DOC_CHARS       默认 500   单文档总字符 < 此值 preflight skip
- TEXT_SIM_PAIR_SCORE_THRESHOLD 默认 0.70  段落对 cosine 相似度 ≥ 此值才进 LLM 候选
- TEXT_SIM_MAX_PAIRS_TO_LLM    默认 30    单 pair 最多发送的段落对数(防 token 爆炸)

读取在每次 run() 调用时进行;L1 测试用 monkeypatch.setenv() 覆盖。
"""

from __future__ import annotations

import os


def min_doc_chars() -> int:
    try:
        return int(os.environ.get("TEXT_SIM_MIN_DOC_CHARS", "500"))
    except ValueError:
        return 500


def pair_score_threshold() -> float:
    try:
        return float(os.environ.get("TEXT_SIM_PAIR_SCORE_THRESHOLD", "0.70"))
    except ValueError:
        return 0.70


def max_pairs_to_llm() -> int:
    try:
        return int(os.environ.get("TEXT_SIM_MAX_PAIRS_TO_LLM", "30"))
    except ValueError:
        return 30


__all__ = ["min_doc_chars", "pair_score_threshold", "max_pairs_to_llm"]
