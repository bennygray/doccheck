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

import hashlib
import re
import unicodedata

import jieba

from app.services.detect.agents.text_sim_impl.models import ParaPair
from app.services.detect.agents.text_sim_impl.stopwords import STOPWORDS

# 纯数字 / 单字符 token 匹配
_NUMERIC_RE = re.compile(r"^[\d\.\,\%]+$")
# 段落原文截断(evidence 持久化前)
_SNIPPET_MAX_CHARS = 200
# hash 旁路:连续空白合并匹配
_WS_RE = re.compile(r"\s+")

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


def _normalize(text: str) -> str:
    """段级 hash 旁路归一化(text-sim-exact-match-bypass D1)。

    NFKC(全角半角) + \\s+ 合并 + strip;与 hash 比对、ironclad 长度判定共享口径。
    """
    return _WS_RE.sub(" ", unicodedata.normalize("NFKC", text)).strip()


_HASH_MIN_NORM_LEN = 20  # 归一化字符 < 此值不进 hash 旁路(避免业主名/章节标题等超短段笛卡尔积爆炸)


def _hash_pairs(
    paras_a: list[str], paras_b: list[str]
) -> tuple[list[ParaPair], set[tuple[int, int]]]:
    """段级 hash 精确匹配旁路(D2 + D3)。

    返:
      hits     : 已构造的 ParaPair 列表(sim=1.0, match_kind='exact_match',
                 a_text/b_text 取归一化前原文截断 200 字)
      hit_set  : 已命中段对的 (a_idx, b_idx) 集合;TF-IDF 候选集需排除(D4)

    最小长度过滤:归一化后字符 < 20 的段不参与 hash 旁路。
    避免"技术方案"/"备注"等通用超短段笛卡尔积爆炸 + 噪声污染。
    超短段仍可走 cosine 路径(若 sim ≥ 阈值)。

    sha1 仅作统一比较键,非密码学需求(可换 blake2b/xxhash 不影响行为)。
    """
    if not paras_a or not paras_b:
        return [], set()

    def _h_or_none(t: str) -> str | None:
        normalized = _normalize(t)
        if len(normalized) < _HASH_MIN_NORM_LEN:
            return None
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()

    a_index: dict[str, list[int]] = {}
    for i, t in enumerate(paras_a):
        h = _h_or_none(t)
        if h is None:
            continue
        a_index.setdefault(h, []).append(i)
    b_index: dict[str, list[int]] = {}
    for j, t in enumerate(paras_b):
        h = _h_or_none(t)
        if h is None:
            continue
        b_index.setdefault(h, []).append(j)

    hits: list[ParaPair] = []
    hit_set: set[tuple[int, int]] = set()
    for h, a_ids in a_index.items():
        b_ids = b_index.get(h)
        if not b_ids:
            continue
        for i in a_ids:
            for j in b_ids:
                hit_set.add((i, j))
                hits.append(
                    ParaPair(
                        a_idx=i,
                        b_idx=j,
                        a_text=paras_a[i][:_SNIPPET_MAX_CHARS],
                        b_text=paras_b[j][:_SNIPPET_MAX_CHARS],
                        sim=1.0,
                        match_kind="exact_match",
                    )
                )
    return hits, hit_set


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

    # text-sim-exact-match-bypass D3: hash 旁路前置,命中段直接 sim=1.0 + label='exact_match'
    hits, hit_set = _hash_pairs(paras_a, paras_b)

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
        return list(hits)

    n_a = len(paras_a)
    mat_a = matrix[:n_a]
    mat_b = matrix[n_a:]

    sim_matrix = cosine_similarity(mat_a, mat_b)

    cosine_pairs: list[ParaPair] = []
    rows, cols = sim_matrix.shape
    for i in range(rows):
        for j in range(cols):
            # D4: cosine 候选集 MUST 排除已 hash 命中的 (a_idx, b_idx) 对
            if (i, j) in hit_set:
                continue
            sim = float(sim_matrix[i, j])
            if sim >= threshold:
                cosine_pairs.append(
                    ParaPair(
                        a_idx=i,
                        b_idx=j,
                        a_text=paras_a[i][:_SNIPPET_MAX_CHARS],
                        b_text=paras_b[j][:_SNIPPET_MAX_CHARS],
                        sim=round(sim, 4),
                        match_kind=None,
                    )
                )
    cosine_pairs.sort(key=lambda p: p.sim, reverse=True)
    return list(hits) + cosine_pairs[:max_pairs]


__all__ = ["jieba_tokenizer", "compute_pair_similarity", "_normalize", "_hash_pairs"]
