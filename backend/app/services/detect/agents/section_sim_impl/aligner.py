"""章节对齐 - title TF-IDF 贪心 + 序号回退 (C8 design D2)

流程:
1. 对所有 (a_title, b_title) 组合算 title-level TF-IDF cosine sim
   (复用 C7 text_sim_impl.tfidf.jieba_tokenizer;但只算 title,不算正文)
2. 贪心匹配:按 sim 降序取 (a_i, b_j) 配对,每章节只能配对一次;
   sim >= threshold 算 aligned_by='title'
3. 未配对的章节按 idx 对齐序号(a_i 配 b_i),aligned_by='index',title_sim 置实际值
4. 返 pair 列表 = min(|chapters_a|, |chapters_b|),多余章节丢弃
"""

from __future__ import annotations

from app.services.detect.agents.section_sim_impl.models import (
    ChapterBlock,
    ChapterPair,
)


def align_chapters(
    chapters_a: list[ChapterBlock],
    chapters_b: list[ChapterBlock],
    threshold: float,
) -> list[ChapterPair]:
    """返对齐配对列表,长度 = min(|a|, |b|)。

    - 任一侧为空 → 返 []
    - 所有 title sim < threshold → 全部走 index 回退
    """
    if not chapters_a or not chapters_b:
        return []

    sim_matrix = _compute_title_sim_matrix(chapters_a, chapters_b)

    n_a = len(chapters_a)
    n_b = len(chapters_b)
    pair_count = min(n_a, n_b)

    # 贪心:按 sim 降序取;每章节只能配对一次
    candidates: list[tuple[float, int, int]] = []
    for i in range(n_a):
        for j in range(n_b):
            candidates.append((sim_matrix[i][j], i, j))
    candidates.sort(key=lambda x: x[0], reverse=True)

    used_a: set[int] = set()
    used_b: set[int] = set()
    pairs: list[ChapterPair] = []

    for sim, i, j in candidates:
        if sim < threshold:
            break
        if i in used_a or j in used_b:
            continue
        pairs.append(
            ChapterPair(a_idx=i, b_idx=j, title_sim=round(sim, 4), aligned_by="title")
        )
        used_a.add(i)
        used_b.add(j)
        if len(pairs) >= pair_count:
            break

    # 剩下的未配对章节按 idx 序号回退
    # 取未用的 a 按 idx 升序 + 未用的 b 按 idx 升序,zip 对齐
    remaining_a = [i for i in range(n_a) if i not in used_a]
    remaining_b = [j for j in range(n_b) if j not in used_b]
    for i, j in zip(remaining_a, remaining_b, strict=False):
        if len(pairs) >= pair_count:
            break
        pairs.append(
            ChapterPair(
                a_idx=i,
                b_idx=j,
                title_sim=round(sim_matrix[i][j], 4),
                aligned_by="index",
            )
        )

    # 按 a_idx 升序返回,便于调用方查看章节顺序
    pairs.sort(key=lambda p: (p.a_idx, p.b_idx))
    return pairs


def _title_tokenizer(text: str) -> list[str]:
    """title 专用 tokenizer:比 body jieba_tokenizer 宽松。

    title 本身短,不能丢 STOPWORDS(如"投标"/"项目"在 title 中是区分词);
    只过滤纯数字、纯标点、空白。单字保留(如"章/节")便于结构词比较。
    """
    import re

    import jieba

    # 仅过滤:纯数字(含小数/逗号/百分号)/ 空白 / 纯标点
    numeric = re.compile(r"^[\d\.\,\%]+$")
    punct = re.compile(r"^[、。,.;:!?\s—\-_\(\)\[\]【】《》""'']+$")
    tokens: list[str] = []
    for tok in jieba.cut(text):
        tok = tok.strip()
        if not tok:
            continue
        if numeric.match(tok):
            continue
        if punct.match(tok):
            continue
        tokens.append(tok)
    return tokens


def _compute_title_sim_matrix(
    chapters_a: list[ChapterBlock], chapters_b: list[ChapterBlock]
) -> list[list[float]]:
    """title × title cosine sim 矩阵。

    延迟 import sklearn(子进程或单测都可快启动);失败(全 token 空)返 0 矩阵。
    """
    titles_a = [c.title for c in chapters_a]
    titles_b = [c.title for c in chapters_b]
    n_a = len(titles_a)
    n_b = len(titles_b)

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    vectorizer = TfidfVectorizer(
        tokenizer=_title_tokenizer,
        token_pattern=None,
        ngram_range=(1, 2),
        min_df=1,
        max_df=1.0,
        max_features=5000,
        lowercase=False,
    )
    try:
        matrix = vectorizer.fit_transform(titles_a + titles_b)
    except ValueError:
        # 所有 title 都被过滤空 → 0 矩阵,触发全 index 回退
        return [[0.0] * n_b for _ in range(n_a)]

    mat_a = matrix[:n_a]
    mat_b = matrix[n_a:]
    sim = cosine_similarity(mat_a, mat_b)
    return [[float(sim[i][j]) for j in range(n_b)] for i in range(n_a)]


__all__ = ["align_chapters"]
