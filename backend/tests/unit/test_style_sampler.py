"""L1 - style_impl/sampler (C13)"""

from __future__ import annotations

import pytest

from app.services.detect.agents.style_impl import sampler
from app.services.detect.agents.style_impl.config import StyleConfig


def _long_para(seed: str, n: int) -> str:
    return seed * n


def test_length_filter_removes_short() -> None:
    """< 100 字被丢;> 300 字被截断。"""
    paragraphs = ["短" * 50, "正常" * 100, "长" * 500]
    out = sampler._length_filter(paragraphs)
    # "短" 50 字太短丢;"正常" 200 字保留;"长" 500 字截到 300
    assert len(out) == 2
    assert len(out[0]) == 200
    assert len(out[1]) == 300


def test_length_filter_empty() -> None:
    assert sampler._length_filter([]) == []


def test_uniform_sample_n_exceeds() -> None:
    paragraphs = ["a", "b"]
    assert sampler._uniform_sample(paragraphs, 5) == ["a", "b"]


def test_uniform_sample_step() -> None:
    paragraphs = [str(i) for i in range(10)]
    sampled = sampler._uniform_sample(paragraphs, 3)
    assert len(sampled) == 3
    # step ≈ 3.3;索引 0, 3, 6
    assert sampled == ["0", "3", "6"]


def test_tfidf_filter_too_few_skips() -> None:
    """段落数 < 3 → 不做 TF-IDF(语料太少)。"""
    paragraphs = ["abc", "def"]
    assert sampler._tfidf_filter(paragraphs, 0.3) == paragraphs


def test_tfidf_filter_ratio_zero_keeps_all() -> None:
    paragraphs = ["甲建设技术方案正文" * 20, "乙建设技术方案正文" * 20, "丙建设技术方案" * 20]
    assert sampler._tfidf_filter(paragraphs, 0.0) == paragraphs


def test_tfidf_filter_normal_case() -> None:
    """TF-IDF 正常工作,返回段落数 <= 原数。"""
    paragraphs = [
        "甲公司建设项目技术方案第一章" * 10,
        "乙公司建设项目技术方案第一章" * 10,
        "行业通用术语描述" * 20,
    ]
    out = sampler._tfidf_filter(paragraphs, 0.3)
    # 具体保留数取决于 IDF 分布,但不应超过原数
    assert len(out) <= len(paragraphs)


@pytest.mark.asyncio
async def test_sample_integrates(monkeypatch) -> None:
    """集成:mock _load_paragraphs 验证完整流水线。"""
    cfg = StyleConfig(sample_per_bidder=5, tfidf_filter_ratio=0.0)

    async def fake_load(_session, _bidder_id):
        # 10 条 200 字段落
        return [f"技术方案段落{i}的详细内容" * 10 for i in range(10)]

    monkeypatch.setattr(sampler, "_load_paragraphs", fake_load)

    sampled, insufficient = await sampler.sample(None, 1, cfg)
    assert len(sampled) == 5
    assert insufficient is False


@pytest.mark.asyncio
async def test_sample_insufficient(monkeypatch) -> None:
    """抽样后 < 3 段 → insufficient=True。"""
    cfg = StyleConfig(sample_per_bidder=5, tfidf_filter_ratio=0.0)

    async def fake_load(_session, _bidder_id):
        # 仅 2 段 100+ 字
        return ["技术段落" * 40, "另一段" * 40]

    monkeypatch.setattr(sampler, "_load_paragraphs", fake_load)

    sampled, insufficient = await sampler.sample(None, 1, cfg)
    assert insufficient is True
