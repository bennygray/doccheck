"""L1 - C9 title_lcs(目录结构维度)"""

from __future__ import annotations

import pytest

from app.services.detect.agents.structure_sim_impl import title_lcs


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("第1章 投标函", "投标函"),
        ("第一章 投标函", "投标函"),
        ("第 3 节 技术方案", "技术方案"),
        ("3.1 技术措施", "技术措施"),
        ("3.1.2 技术保障", "技术保障"),
        ("一、投标人须知", "投标人须知"),
        ("1、投标函", "投标函"),
        ("1. 投标函", "投标函"),
        ("  第  2  章  商务部分  ", "商务部分"),
    ],
)
def test_normalize_title_strips_prefix(raw, expected):
    assert title_lcs._normalize_title(raw) == expected


def test_normalize_title_strips_punct_and_whitespace():
    assert title_lcs._normalize_title("投标、函 / 技术:方案") == "投标函技术方案"


def test_normalize_title_empty():
    assert title_lcs._normalize_title("") == ""
    assert title_lcs._normalize_title("   ") == ""


def test_lcs_length_basic():
    # 经典 LCS 案例
    assert title_lcs._lcs_length(list("ABCBDAB"), list("BDCAB")) == 4
    assert title_lcs._lcs_length(list("ABC"), list("ABC")) == 3
    assert title_lcs._lcs_length(list("ABC"), list("DEF")) == 0
    assert title_lcs._lcs_length([], list("ABC")) == 0


def test_lcs_length_order_sensitive():
    # LCS 保留顺序
    assert title_lcs._lcs_length(["A", "B", "C"], ["C", "B", "A"]) == 1


@pytest.mark.asyncio
async def test_compute_directory_similarity_identical():
    titles = ["第1章 投标函", "第2章 投标须知", "第3章 技术方案", "第4章 报价"]
    r = await title_lcs.compute_directory_similarity(titles, titles[:])
    assert r is not None
    assert r.score == 1.0
    assert r.lcs_length == 4
    assert r.titles_a_count == 4
    assert r.titles_b_count == 4
    assert len(r.sample_titles_matched) == 4


@pytest.mark.asyncio
async def test_compute_directory_similarity_different_prefix_same_essence():
    """目录归一化后相同(不同序号编号)→ LCS=4。"""
    a = ["第1章 投标函", "第2章 技术方案", "第3章 商务", "第4章 报价"]
    b = ["一、投标函", "二、技术方案", "三、商务", "四、报价"]
    r = await title_lcs.compute_directory_similarity(a, b)
    assert r is not None
    assert r.lcs_length == 4
    assert r.score == 1.0


@pytest.mark.asyncio
async def test_compute_directory_similarity_completely_different():
    a = ["第1章 投标函", "第2章 技术方案", "第3章 报价"]
    b = ["第1章 商务响应", "第2章 资格证明", "第3章 施工方案"]
    r = await title_lcs.compute_directory_similarity(a, b)
    assert r is not None
    assert r.lcs_length == 0
    assert r.score == 0.0


@pytest.mark.asyncio
async def test_compute_directory_similarity_too_few_chapters(monkeypatch):
    monkeypatch.delenv("STRUCTURE_SIM_MIN_CHAPTERS", raising=False)  # default 3
    # 单侧 2 章节 < 3 → None
    r = await title_lcs.compute_directory_similarity(
        ["第1章 A", "第2章 B"],
        ["第1章 A", "第2章 B", "第3章 C"],
    )
    assert r is None


@pytest.mark.asyncio
async def test_compute_directory_similarity_env_min_chapters(monkeypatch):
    monkeypatch.setenv("STRUCTURE_SIM_MIN_CHAPTERS", "5")
    titles = ["第1章 A", "第2章 B", "第3章 C", "第4章 D"]  # 4 < 5
    r = await title_lcs.compute_directory_similarity(titles, titles)
    assert r is None


@pytest.mark.asyncio
async def test_compute_directory_similarity_partial_overlap():
    a = ["第1章 投标函", "第2章 技术方案", "第3章 商务响应", "第4章 报价"]
    b = ["第1章 投标函", "第2章 合同条款", "第3章 技术方案", "第4章 报价"]
    # LCS = ["投标函", "技术方案", "报价"] = 3
    r = await title_lcs.compute_directory_similarity(a, b)
    assert r is not None
    assert r.lcs_length == 3
    assert abs(r.score - (2 * 3 / 8)) < 1e-6  # 0.75
