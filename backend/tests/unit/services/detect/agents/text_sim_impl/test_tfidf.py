"""L1 - text_sim_impl.tfidf 单元测试 (C7)

只测纯同步函数;不走 ProcessPoolExecutor。
"""

from __future__ import annotations

from app.services.detect.agents.text_sim_impl.tfidf import (
    compute_pair_similarity,
    jieba_tokenizer,
)


def test_jieba_tokenizer_basic():
    tokens = jieba_tokenizer("人工智能技术方案")
    assert len(tokens) > 0
    # 停用词 / 单字 过滤后,至少含"人工智能"或"技术方案"之一
    assert any(len(t) >= 2 for t in tokens)


def test_jieba_tokenizer_filters_numbers_and_stopwords():
    tokens = jieba_tokenizer("本项目的 12345 和 0.5")
    # "的" "和" "本" "项目" 都在 STOPWORDS;"12345" "0.5" 数字过滤
    # 剩余可能为空或极少
    for t in tokens:
        assert not t.isdigit()
        assert "." not in t or not t.replace(".", "").isdigit()


def test_compute_pair_similarity_empty_returns_empty():
    assert compute_pair_similarity([], [], 0.5, 30) == []
    assert compute_pair_similarity(["abc" * 10], [], 0.5, 30) == []
    assert compute_pair_similarity([], ["abc" * 10], 0.5, 30) == []


def test_compute_pair_similarity_identical_paragraphs_high_sim():
    text = "本项目采用先进的人工智能技术方案,实现自动化检测。" * 3
    pairs = compute_pair_similarity([text], [text], 0.5, 30)
    assert len(pairs) == 1
    assert pairs[0].sim > 0.95
    assert pairs[0].a_idx == 0 and pairs[0].b_idx == 0


def test_compute_pair_similarity_unrelated_no_pairs():
    a = "本项目涉及道路桥梁施工养护工程需要大量钢筋水泥"
    b = "饮食搭配均衡蔬菜水果富含维生素对身体健康有益"
    pairs = compute_pair_similarity([a], [b], 0.5, 30)
    assert pairs == []


def test_compute_pair_similarity_threshold_filter():
    """threshold 边界:相同段落 sim=1.0,threshold=2.0 → 无 pair。"""
    text = "本项目采用先进的人工智能技术方案"
    pairs = compute_pair_similarity([text], [text], 2.0, 30)
    assert pairs == []


def test_compute_pair_similarity_sorted_desc():
    """返结果按 sim 降序。"""
    # 3 段 vs 3 段,两段 identical,一段完全不同
    base = "本项目技术方案采用人工智能算法实现自动化围标检测和证据收集"
    alt = "饮食均衡对身体健康有益建议搭配蔬菜水果"
    a_paras = [base, base + " v2", alt]
    b_paras = [base, base + " v2", alt]
    pairs = compute_pair_similarity(a_paras, b_paras, 0.3, 30)
    # 应该有多对
    assert len(pairs) >= 2
    sims = [p.sim for p in pairs]
    assert sims == sorted(sims, reverse=True)


def test_compute_pair_similarity_max_pairs_truncate():
    base = "本项目技术方案采用人工智能算法实现自动化检测和证据收集"
    pairs = compute_pair_similarity([base] * 5, [base] * 5, 0.5, 3)
    assert len(pairs) == 3
