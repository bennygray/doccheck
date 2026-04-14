"""TF-IDF + cosine 段落对相似度计算 (C7 detect-agent-text-similarity)

同步纯函数入口 `compute_pair_similarity`,可 pickle 进 ProcessPoolExecutor
子进程。子进程内 new TfidfVectorizer,不跨进程传递。

算法要点(对齐 design D2):
- jieba.cut 分词 + 去停用词 + 过滤纯数字/单字符 token
- TfidfVectorizer(ngram_range=(1,2), min_df=1, max_df=0.95, max_features=20000)
- 联合 A/B 全部段落 fit_transform → 统一词表
- cosine_similarity(mat_a, mat_b) → (|A|, |B|) 矩阵
- 枚举 i,j 取 sim >= threshold 的段落对,按 sim 降序截前 max_pairs
"""

from __future__ import annotations

import re

import jieba

from app.services.detect.agents.text_sim_impl.models import ParaPair
from app.services.detect.agents.text_sim_impl.stopwords import STOPWORDS

# 纯数字 / 单字符 token 匹配
_NUMERIC_RE = re.compile(r"^[\d\.\,\%]+$")
# 段落原文截断(evidence 持久化前)
_SNIPPET_MAX_CHARS = 200

# TF-IDF 超参数
_MAX_FEATURES = 20000
_MIN_DF = 1
# max_df=1.0 避免短样本(总段数 < 10)时全部词被过滤
# STOPWORDS + 单字过滤已处理"过于常见词"场景,无需 max_df 二次过滤
_MAX_DF = 1.0
_NGRAM_RANGE = (1, 2)

_JIEBA_INITIALIZED = False


def _ensure_jieba_initialized() -> None:
    """首次调用触发 jieba 词典加载;idempotent。"""
    global _JIEBA_INITIALIZED
    if not _JIEBA_INITIALIZED:
        jieba.initialize()
        _JIEBA_INITIALIZED = True


def jieba_tokenizer(text: str) -> list[str]:
    """jieba.cut + 去停用词 + 过滤数字/单字符 token。"""
    _ensure_jieba_initialized()
    tokens: list[str] = []
    for tok in jieba.cut(text):
        tok = tok.strip()
        if not tok:
            continue
        if len(tok) < 2:
            continue  # 单字符噪声大
        if tok in STOPWORDS:
            continue
        if _NUMERIC_RE.match(tok):
            continue
        tokens.append(tok)
    return tokens


def compute_pair_similarity(
    paras_a: list[str],
    paras_b: list[str],
    threshold: float,
    max_pairs: int,
) -> list[ParaPair]:
    """纯函数 — 返超阈值段落对,按 sim 降序,最多 max_pairs 条。

    边界:
    - 任一侧为空 → 返 []
    - fit_transform 抛异常(如词表全空)→ 返 []
    """
    if not paras_a or not paras_b:
        return []

    # 延迟 import sklearn,减少模块加载开销(子进程 import 一次即可)
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    vectorizer = TfidfVectorizer(
        tokenizer=jieba_tokenizer,
        token_pattern=None,  # 告诉 sklearn 用 tokenizer,抑制警告
        ngram_range=_NGRAM_RANGE,
        min_df=_MIN_DF,
        max_df=_MAX_DF,
        max_features=_MAX_FEATURES,
        lowercase=False,  # 中文无需小写
    )
    all_paras = paras_a + paras_b
    try:
        matrix = vectorizer.fit_transform(all_paras)
    except ValueError:
        # 极端:分词后全部被过滤,词表空
        return []

    n_a = len(paras_a)
    mat_a = matrix[:n_a]
    mat_b = matrix[n_a:]

    sim_matrix = cosine_similarity(mat_a, mat_b)

    pairs: list[ParaPair] = []
    rows, cols = sim_matrix.shape
    for i in range(rows):
        for j in range(cols):
            sim = float(sim_matrix[i, j])
            if sim >= threshold:
                pairs.append(
                    ParaPair(
                        a_idx=i,
                        b_idx=j,
                        a_text=paras_a[i][:_SNIPPET_MAX_CHARS],
                        b_text=paras_b[j][:_SNIPPET_MAX_CHARS],
                        sim=round(sim, 4),
                    )
                )
    pairs.sort(key=lambda p: p.sim, reverse=True)
    return pairs[:max_pairs]


__all__ = ["jieba_tokenizer", "compute_pair_similarity"]
