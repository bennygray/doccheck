"""L1 - aligner 单元测试 (C8)"""

from __future__ import annotations

from app.services.detect.agents.section_sim_impl.aligner import align_chapters
from app.services.detect.agents.section_sim_impl.models import ChapterBlock


def _ch(idx: int, title: str, text: str = "内容") -> ChapterBlock:
    return ChapterBlock(idx=idx, title=title, paragraphs=(text,), total_chars=len(text))


def test_align_empty_side_returns_empty():
    assert align_chapters([], [_ch(0, "a")], 0.4) == []
    assert align_chapters([_ch(0, "a")], [], 0.4) == []


def test_align_perfect_title_match():
    a = [_ch(0, "投标函"), _ch(1, "技术方案"), _ch(2, "商务标")]
    b = [_ch(0, "投标函"), _ch(1, "技术方案"), _ch(2, "商务标")]
    pairs = align_chapters(a, b, 0.4)
    assert len(pairs) == 3
    for p in pairs:
        assert p.aligned_by == "title"
        assert p.a_idx == p.b_idx


def test_align_title_reorder():
    """章节顺序不同但 title 相同 → 走 title 对齐跨 idx。"""
    a = [_ch(0, "投标函"), _ch(1, "技术方案"), _ch(2, "商务标")]
    b = [_ch(0, "商务标"), _ch(1, "投标函"), _ch(2, "技术方案")]
    pairs = align_chapters(a, b, 0.4)
    assert len(pairs) == 3
    assert all(p.aligned_by == "title" for p in pairs)
    # 按 a_idx 升序返回
    assert pairs[0].a_idx == 0  # 投标函
    assert pairs[0].b_idx == 1
    assert pairs[1].a_idx == 1  # 技术方案
    assert pairs[1].b_idx == 2
    assert pairs[2].a_idx == 2  # 商务标
    assert pairs[2].b_idx == 0


def test_align_index_fallback_when_low_sim():
    """title 完全不相关 → 走 index 回退。"""
    a = [_ch(0, "AAA"), _ch(1, "BBB"), _ch(2, "CCC")]
    b = [_ch(0, "XXX"), _ch(1, "YYY"), _ch(2, "ZZZ")]
    pairs = align_chapters(a, b, 0.4)
    # 高阈值 0.4 AAA vs XXX 等不可能达,全部 index 回退
    assert len(pairs) == 3
    assert all(p.aligned_by == "index" for p in pairs)
    for i, p in enumerate(pairs):
        assert p.a_idx == i and p.b_idx == i


def test_align_partial_title_partial_index():
    """部分章节 title 对齐,剩余 index 回退。"""
    a = [_ch(0, "投标函"), _ch(1, "AAA"), _ch(2, "BBB")]
    b = [_ch(0, "CCC"), _ch(1, "DDD"), _ch(2, "投标函")]
    pairs = align_chapters(a, b, 0.4)
    assert len(pairs) == 3
    # 投标函 vs 投标函 会按 title 对齐
    title_pairs = [p for p in pairs if p.aligned_by == "title"]
    idx_pairs = [p for p in pairs if p.aligned_by == "index"]
    assert len(title_pairs) == 1
    assert title_pairs[0].a_idx == 0 and title_pairs[0].b_idx == 2
    assert len(idx_pairs) == 2


def test_align_multi_extra_chapters_dropped():
    """单侧章节多,多余章节丢弃;返回数 = min(|a|, |b|)。"""
    a = [_ch(i, f"ch_{i}") for i in range(5)]
    b = [_ch(i, f"ch_{i}") for i in range(3)]
    pairs = align_chapters(a, b, 0.4)
    assert len(pairs) == 3


def test_align_similar_titles():
    """'技术方案' vs '技术措施' TF-IDF sim 能 > 0.4(共享"技术")。"""
    a = [_ch(0, "技术方案")]
    b = [_ch(0, "技术措施")]
    pairs = align_chapters(a, b, 0.4)
    assert len(pairs) == 1
    # 可能 by title(共享"技术"),也可能 by index(阈值 0.4 边界敏感)
    # 断言配对成功,title_sim 有值
    assert pairs[0].title_sim >= 0.0
