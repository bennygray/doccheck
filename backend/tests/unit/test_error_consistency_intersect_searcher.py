"""L1 - error_impl/intersect_searcher (C13)

测试单向扫描 / 双向命中 / paragraphs+header_footer 并集 / 截断逻辑。
不依赖真实 DB —— 用 monkeypatch 替换 _load_segments。
"""

from __future__ import annotations

import pytest

from app.services.detect.agents.error_impl import intersect_searcher
from app.services.detect.agents.error_impl.config import (
    ErrorConsistencyConfig,
)


@pytest.mark.asyncio
async def test_bidirectional_hit(monkeypatch) -> None:
    """A 关键词命中 B,B 关键词命中 A。"""
    cfg = ErrorConsistencyConfig(max_candidate_segments=100)

    async def fake_load(_session, bidder_id):
        if bidder_id == 1:
            return [(101, 11, "technical", "body", "这里出现了乙公司的内容")]
        return [(201, 22, "technical", "body", "这段含张三的名字")]

    monkeypatch.setattr(intersect_searcher, "_load_segments", fake_load)

    hits, truncated, original = await intersect_searcher.search(
        None, 1, 2, ["张三"], ["乙公司"], cfg
    )
    assert truncated is False
    assert original == 2
    assert len(hits) == 2
    sources = sorted([h["source_bidder_id"] for h in hits])
    assert sources == [1, 2]


@pytest.mark.asyncio
async def test_body_hit(monkeypatch) -> None:
    cfg = ErrorConsistencyConfig(max_candidate_segments=100)

    async def fake_load(_session, bidder_id):
        return [(201, 22, "technical", "body", "这段含 AB123 资质号")]

    monkeypatch.setattr(intersect_searcher, "_load_segments", fake_load)
    hits, _, _ = await intersect_searcher.search(
        None, 1, 2, ["AB123"], [], cfg
    )
    assert len(hits) == 1
    assert hits[0]["position"] == "body"
    assert "AB123" in hits[0]["matched_keywords"]


@pytest.mark.asyncio
async def test_header_footer_hit(monkeypatch) -> None:
    cfg = ErrorConsistencyConfig(max_candidate_segments=100)

    async def fake_load(_session, bidder_id):
        return [
            (300, 33, "technical", "header", "页眉:乙公司"),
            (301, 33, "technical", "footer", "页脚:乙公司"),
        ]

    monkeypatch.setattr(intersect_searcher, "_load_segments", fake_load)
    hits, _, _ = await intersect_searcher.search(
        None, 1, 2, ["乙公司"], [], cfg
    )
    assert len(hits) == 2
    positions = sorted([h["position"] for h in hits])
    assert positions == ["footer", "header"]


@pytest.mark.asyncio
async def test_no_hit_returns_empty(monkeypatch) -> None:
    cfg = ErrorConsistencyConfig(max_candidate_segments=100)

    async def fake_load(_session, bidder_id):
        return [(1, 1, "technical", "body", "完全无关内容")]

    monkeypatch.setattr(intersect_searcher, "_load_segments", fake_load)
    hits, truncated, original = await intersect_searcher.search(
        None, 1, 2, ["张三"], ["李四"], cfg
    )
    assert hits == []
    assert truncated is False
    assert original == 0


@pytest.mark.asyncio
async def test_max_candidate_truncate(monkeypatch) -> None:
    """命中超 cap → 截断按 matched_keywords 数倒序。"""
    cfg = ErrorConsistencyConfig(max_candidate_segments=2)

    async def fake_load(_session, bidder_id):
        return [
            (i, 100 + i, "technical", "body", f"命中 张三 段落{i}")
            for i in range(5)
        ]

    monkeypatch.setattr(intersect_searcher, "_load_segments", fake_load)
    hits, truncated, original = await intersect_searcher.search(
        None, 1, 2, ["张三"], [], cfg
    )
    assert truncated is True
    assert original == 5
    assert len(hits) == 2


@pytest.mark.asyncio
async def test_truncate_prefers_more_keywords(monkeypatch) -> None:
    """同段命中关键词多的优先保留。"""
    cfg = ErrorConsistencyConfig(max_candidate_segments=2)

    async def fake_load(_session, bidder_id):
        return [
            (1, 100, "technical", "body", "只命中 张三"),
            (2, 100, "technical", "body", "命中 张三 李四 王五"),
            (3, 100, "technical", "body", "只命中 李四"),
        ]

    monkeypatch.setattr(intersect_searcher, "_load_segments", fake_load)
    hits, truncated, _ = await intersect_searcher.search(
        None, 1, 2, ["张三", "李四", "王五"], [], cfg
    )
    assert truncated is True
    assert len(hits) == 2
    # 第一条应该是 3 个关键词命中的
    assert "王五" in hits[0]["matched_keywords"]


@pytest.mark.asyncio
async def test_empty_keywords_skip_load(monkeypatch) -> None:
    """双方关键词都空 → 不查 DB,直接返空。"""
    cfg = ErrorConsistencyConfig(max_candidate_segments=100)

    call_count = {"n": 0}

    async def fake_load(_session, bidder_id):
        call_count["n"] += 1
        return []

    monkeypatch.setattr(intersect_searcher, "_load_segments", fake_load)
    hits, _, _ = await intersect_searcher.search(
        None, 1, 2, [], [], cfg
    )
    assert hits == []
    assert call_count["n"] == 0


@pytest.mark.asyncio
async def test_textbox_table_row_normalized_to_body(monkeypatch) -> None:
    """textbox / table_row 等位置归类为 body 大类。"""
    cfg = ErrorConsistencyConfig(max_candidate_segments=100)

    async def fake_load(_session, bidder_id):
        return [
            (1, 1, "technical", "textbox", "文本框含 张三"),
            (2, 1, "technical", "table_row", "表格行含 张三"),
        ]

    monkeypatch.setattr(intersect_searcher, "_load_segments", fake_load)
    hits, _, _ = await intersect_searcher.search(
        None, 1, 2, ["张三"], [], cfg
    )
    assert all(h["position"] == "body" for h in hits)
