"""L1 - section_similarity scorer 批量化契约 (fix-section-similarity-spawn-loop)

锁两条契约:
1. compute_all_pair_sims_batch 结果与 N 次单调 c7_tfidf.compute_pair_similarity 完全一致
2. scorer.score_all_chapter_pairs 内 run_isolated 调用次数 = 1(防回归到 per-pair spawn)

Case 2 是核心防回归契约 — 锁死"批量化"的代码路径,未来任何把循环改回 per-pair 的 PR 都会红测。
"""

from __future__ import annotations

import pytest

from app.services.detect.agents.section_sim_impl import scorer as scorer_mod
from app.services.detect.agents.section_sim_impl.models import (
    ChapterBlock,
    ChapterPair,
)
from app.services.detect.agents.text_sim_impl import tfidf as c7_tfidf


def _synth_paragraphs(seed: int, n: int) -> list[str]:
    """构造 n 段中文段落,seed 影响词分布(不同章节产出不同段落)。"""
    base_words = (
        "投标 文件 技术 方案 监理 工程 质量 安全 进度 控制 方法 要求 "
        "标准 规范 程序 措施 检查 验收 资料 报告 现场 管理 体系 制度"
    ).split()
    paras: list[str] = []
    for i in range(n):
        # 用 seed + i 决定取词起点,保证段落间有重复词(jieba 分词后相似度可计算)
        start = (seed * 7 + i * 3) % len(base_words)
        words = [base_words[(start + k) % len(base_words)] for k in range(8)]
        paras.append(" ".join(words))
    return paras


def test_batch_helper_results_equivalent_to_per_pair():
    """compute_all_pair_sims_batch N 个章节对一次性算结果,与 N 次单调 c7_tfidf 完全一致。

    防止未来重构 helper 时改变算法语义(如改了循环顺序、误传参数顺序、漏字段)。
    """
    threshold = 0.3
    max_pairs = 50

    # 构造 3 个章节对的段落数据(每章 5 段)
    chapter_pair_data: list[tuple[list[str], list[str]]] = [
        (_synth_paragraphs(seed=1, n=5), _synth_paragraphs(seed=2, n=5)),
        (_synth_paragraphs(seed=3, n=4), _synth_paragraphs(seed=4, n=4)),
        (_synth_paragraphs(seed=5, n=6), _synth_paragraphs(seed=6, n=6)),
    ]

    # 路径 A:批量
    batch_results = scorer_mod.compute_all_pair_sims_batch(
        chapter_pair_data, threshold, max_pairs
    )

    # 路径 B:N 次单调
    per_pair_results = [
        c7_tfidf.compute_pair_similarity(a, b, threshold, max_pairs)
        for a, b in chapter_pair_data
    ]

    assert len(batch_results) == len(per_pair_results) == 3
    for batch_pairs, single_pairs in zip(batch_results, per_pair_results, strict=True):
        assert len(batch_pairs) == len(single_pairs)
        for bp, sp in zip(batch_pairs, single_pairs, strict=True):
            # ParaPair 是 frozen dataclass,可直接 ==
            assert bp == sp


@pytest.mark.asyncio
async def test_scorer_calls_run_isolated_exactly_once(monkeypatch: pytest.MonkeyPatch):
    """**核心防回归契约**:scorer.score_all_chapter_pairs 内 run_isolated 调用次数 = 1。

    fix-section-similarity-spawn-loop 的关键不变量 — 未来任何把循环改回 per-pair
    `await run_isolated(...)` 的 PR 必须红测。
    """
    call_counter = {"count": 0}

    async def fake_run_isolated(func, *args, timeout):
        """计数 fake — 直接在主进程跑函数,不走真 spawn。"""
        call_counter["count"] += 1
        # 不走真 spawn,主进程直接调用
        return func(*args)

    monkeypatch.setattr(scorer_mod, "run_isolated", fake_run_isolated)

    # 构造 5 个章节对的 fixture
    chapters_a = [
        ChapterBlock(
            idx=i,
            title=f"第{i+1}章 测试",
            paragraphs=tuple(_synth_paragraphs(seed=i, n=4)),
            total_chars=200,
        )
        for i in range(5)
    ]
    chapters_b = [
        ChapterBlock(
            idx=i,
            title=f"第{i+1}章 测试",
            paragraphs=tuple(_synth_paragraphs(seed=i + 10, n=4)),
            total_chars=200,
        )
        for i in range(5)
    ]
    chapter_pairs = [
        ChapterPair(a_idx=i, b_idx=i, title_sim=1.0, aligned_by="title")
        for i in range(5)
    ]

    # llm_provider=None 时:若 selected_pairs 非空会尝试调 LLM 拿 None 错;
    # 但这里阈值 0.3 + 合成段落相似度通常很低,大多数 selected_pairs 为空走"未检出"路径,
    # 即使少数命中也会因 None provider 抛 — 用 stub 兜底。
    class _NullProvider:
        name = "null"

        async def complete(self, messages, **kwargs):
            from app.services.llm.base import LLMResult

            # 返合法 JSON 让 llm_judge 不抛
            return LLMResult(text='{"overall": "ok", "confidence": "low", "judgments": {}}', error=None)

    await scorer_mod.score_all_chapter_pairs(
        chapters_a=chapters_a,
        chapters_b=chapters_b,
        chapter_pairs=chapter_pairs,
        llm_provider=_NullProvider(),
        bidder_a_name="甲",
        bidder_b_name="乙",
        doc_role="technical",
    )

    assert call_counter["count"] == 1, (
        f"run_isolated 调用 {call_counter['count']} 次,应为 1。"
        "fix-section-similarity-spawn-loop 契约要求批量化 — N 次 spawn 退化必踩 jieba"
        "冷启动 N 次,Windows 上 N>50 章节对必撞 300s timeout。"
        "如果你确实有需求改回 per-pair,先去改 spec 'ProcessPool per-task 进程隔离' "
        "Requirement 的批量化 scenario 并写明理由。"
    )


@pytest.mark.asyncio
async def test_scorer_empty_chapter_pairs_skips_run_isolated(
    monkeypatch: pytest.MonkeyPatch,
):
    """空 chapter_pairs 不应 spawn(short-circuit)— 极端边界防御。"""
    call_counter = {"count": 0}

    async def fake_run_isolated(func, *args, timeout):
        call_counter["count"] += 1
        return func(*args)

    monkeypatch.setattr(scorer_mod, "run_isolated", fake_run_isolated)

    class _NullProvider:
        name = "null"

        async def complete(self, messages, **kwargs):
            from app.services.llm.base import LLMResult

            return LLMResult(text='{"overall": "ok", "confidence": "low", "judgments": {}}', error=None)

    await scorer_mod.score_all_chapter_pairs(
        chapters_a=[],
        chapters_b=[],
        chapter_pairs=[],
        llm_provider=_NullProvider(),
        bidder_a_name="甲",
        bidder_b_name="乙",
        doc_role="technical",
    )

    assert call_counter["count"] == 0, (
        f"空 chapter_pairs 仍 spawn 了 {call_counter['count']} 次,应为 0(short-circuit)"
    )
