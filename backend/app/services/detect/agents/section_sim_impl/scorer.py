"""章节对评分(复用 C7 text_sim_impl)- C8 design D3

对每个对齐章节对:
1. 章节内段落级 TF-IDF + cosine(C7 tfidf.compute_pair_similarity)→ para_pairs
2. 所有章节的 para_pairs 合并 → 按 title_sim × avg_para_sim 粗排截前 MAX_PAIRS_TO_LLM
3. 一次 LLM 调用(C7 llm_judge.call_llm_judge)给全部送审段落对定性
4. 回落到各章节:聚合本章节的 judgments → 算 chapter_score + is_chapter_ironclad

detect-tender-baseline §4 章节级 baseline 接入:
- 章节标题 hash ∈ baseline → 整章节 is_chapter_ironclad=False(章节是模板)
- 章节内 sample 段 hash ∈ baseline → 段被标 baseline_matched(供前端段级灰底)
  + 段级 ironclad 跳过(复用 §3 compute_is_ironclad 的 baseline_excluded 路径)
"""

from __future__ import annotations

from app.core.config import settings
from app.services.detect.agents._subprocess import run_isolated
from app.services.detect.agents.section_sim_impl.models import (
    ChapterBlock,
    ChapterPair,
    ChapterScoreResult,
)
from app.services.detect.agents.text_sim_impl import (
    aggregator as c7_aggregator,
)
from app.services.detect.agents.text_sim_impl import (
    config as c7_config,
)
from app.services.detect.agents.text_sim_impl import (
    llm_judge as c7_llm_judge,
)
from app.services.detect.agents.text_sim_impl import (
    tfidf as c7_tfidf,
)
from app.services.detect.agents.text_sim_impl.models import ParaPair
from app.services.llm.base import LLMProvider

# 每章节在 evidence_json.chapter_pairs[*].samples 上限
_CHAPTER_SAMPLES_LIMIT = 15

# detect-tender-baseline §4:baseline_source 优先级(与 §3 aggregator 对齐)
_BASELINE_SOURCE_PRIORITY: dict[str, int] = {
    "tender": 3, "consensus": 2, "none": 0
}


def compute_all_pair_sims_batch(
    chapter_pair_data: list[tuple[list[str], list[str]]],
    threshold: float,
    max_pairs: int,
) -> list[list[ParaPair]]:
    """子进程内批量执行 N 个章节对的 TF-IDF(fix-section-similarity-spawn-loop)。

    必须 module-level(spawn 走 pickle by name,nested 函数不可 pickle)。
    用法:整个 chapter_pair_data 一次性传给单个 run_isolated 调用,
    子进程内串行循环 N 次纯计算;jieba 词典 / numpy / sklearn import 仅一次。
    替换前 scorer per-pair spawn 路径(实测 N=80 撞 300s,批量后 ~55s)。
    """
    return [
        c7_tfidf.compute_pair_similarity(a_paras, b_paras, threshold, max_pairs)
        for a_paras, b_paras in chapter_pair_data
    ]


async def score_all_chapter_pairs(
    chapters_a: list[ChapterBlock],
    chapters_b: list[ChapterBlock],
    chapter_pairs: list[ChapterPair],
    llm_provider: LLMProvider | None,
    bidder_a_name: str,
    bidder_b_name: str,
    doc_role: str,
    *,
    baseline_hash_to_source: dict[str, str] | None = None,
) -> tuple[list[ChapterScoreResult], list[ParaPair], dict[int, str], dict | None]:
    """对所有章节对评分,返 (chapter_results, all_para_pairs, all_judgments, ai_meta)。

    all_* 用于 evidence_json 跨章节汇总字段。

    detect-tender-baseline §4 keyword-only `baseline_hash_to_source`:
    - 章节标题 hash ∈ baseline → 该章节对 chapter_baseline_source 标 source,
      is_chapter_ironclad=False(整章节是模板,即使 LLM 判 plagiarism 也不顶铁证)
    - 章节内 sample 段 hash ∈ baseline → sample.baseline_matched=True + source 段级
    - compute_is_ironclad 收到 baseline_excluded_segment_hashes → ≥50 字 exact_match
      段被跳过(§3 同 path)
    - 不传(老调用)→ 行为完全等价于 §4 前
    """
    hash_to_source = baseline_hash_to_source or {}
    baseline_set = set(hash_to_source.keys())
    threshold = c7_config.pair_score_threshold()
    max_pairs_to_llm = c7_config.max_pairs_to_llm()

    # 1) 每章节对算段落级相似度(CPU 密集,走 executor)
    # harden-async-infra F1:per-task 子进程隔离
    # fix-section-similarity-spawn-loop:批量化 — N 次 spawn(N 次 jieba 冷启动 ~3s/次)
    # 改为单次 spawn 内串行 N 次纯计算,jieba/numpy/sklearn 只加载一次。
    if chapter_pairs:
        chapter_pair_data: list[tuple[list[str], list[str]]] = [
            (
                list(chapters_a[cp.a_idx].paragraphs),
                list(chapters_b[cp.b_idx].paragraphs),
            )
            for cp in chapter_pairs
        ]
        per_chapter_pairs: list[list[ParaPair]] = await run_isolated(
            compute_all_pair_sims_batch,
            chapter_pair_data,
            threshold,
            # 章节内也设上限,防单章节段落爆(粗 max,跨章节再统一截 max_pairs_to_llm)
            max_pairs_to_llm,
            timeout=settings.agent_subprocess_timeout,
        )
    else:
        per_chapter_pairs = []

    # 2) 合并所有段落对,按 "章节 title_sim × 段落 sim" 粗排,截前 max_pairs_to_llm
    all_ranked: list[tuple[float, int, ParaPair]] = []
    for ch_idx, (cp, pairs) in enumerate(
        zip(chapter_pairs, per_chapter_pairs, strict=True)
    ):
        for p in pairs:
            # +0.1 防 title_sim=0 时整章节被压到最底
            rank = (cp.title_sim + 0.1) * p.sim
            all_ranked.append((rank, ch_idx, p))
    all_ranked.sort(key=lambda x: x[0], reverse=True)
    selected = all_ranked[:max_pairs_to_llm]

    # 维护章节 → 在 selected 中的局部 idx 映射,供回落 judgments
    selected_pairs: list[ParaPair] = []
    selected_ch_idx: list[int] = []
    for _, ch_idx, p in selected:
        selected_pairs.append(p)
        selected_ch_idx.append(ch_idx)

    # 3) 一次 LLM 调用(若 selected_pairs 为空则跳过)
    if selected_pairs:
        judgments, ai_meta = await c7_llm_judge.call_llm_judge(
            llm_provider,
            bidder_a_name,
            bidder_b_name,
            f"section:{doc_role}",
            selected_pairs,
        )
    else:
        judgments, ai_meta = {}, {"overall": "未检出超阈值段落对", "confidence": "high"}

    # 4) 回落每章节:收集本章节在 selected 中出现的 pairs 和 judgments
    chapter_results: list[ChapterScoreResult] = []
    for ch_idx, (cp, pairs) in enumerate(
        zip(chapter_pairs, per_chapter_pairs, strict=True)
    ):
        # 本章节在 selected 中的全部(idx_in_selected → judgment)
        local_judgments: dict[int, str] = {}
        local_pairs_in_selected: list[ParaPair] = []
        for sel_idx, sel_ch in enumerate(selected_ch_idx):
            if sel_ch == ch_idx:
                local_pairs_in_selected.append(selected_pairs[sel_idx])
                j = judgments.get(sel_idx)
                if j is not None:
                    # 对齐到本章节局部 idx
                    local_judgments[len(local_pairs_in_selected) - 1] = j

        # 本章节所有 pairs 算分 — 选进 selected 的用 judgments,未选进的按 None 权重
        # 简化:用 selected 内的 local_pairs_in_selected + local_judgments 算分
        # (未送审的段落对被视为 generic 权重 0.2 太乐观,按 None 权重 0.3 更保守)
        # 方案:把未 selected 的 pair 补成 "None judgment" 加入 local 列表
        unselected = [p for p in pairs if p not in local_pairs_in_selected]
        combined_pairs = local_pairs_in_selected + unselected
        combined_judgments = dict(local_judgments)  # 未 selected 的无 judgment,保留缺失

        if combined_pairs:
            chapter_score = c7_aggregator.aggregate_pair_score(
                combined_pairs, combined_judgments
            )
        else:
            chapter_score = 0.0

        ca = chapters_a[cp.a_idx]
        cb = chapters_b[cp.b_idx]

        # detect-tender-baseline §4:章节级 baseline 判定 — 章节标题 hash 命中
        # → 整章节 is_chapter_ironclad=False(章节是模板)
        chapter_baseline_source = "none"
        chapter_baseline_matched = False
        if baseline_set:
            for title in (ca.title, cb.title):
                if not title:
                    continue
                h = c7_aggregator._segment_hash_for(title)
                if h in baseline_set:
                    chapter_baseline_matched = True
                    src = hash_to_source.get(h, "none")
                    if (
                        _BASELINE_SOURCE_PRIORITY[src]
                        > _BASELINE_SOURCE_PRIORITY[chapter_baseline_source]
                    ):
                        chapter_baseline_source = src

        # 段级 ironclad 跳过(§3 同 path);章节级命中再覆盖整体
        is_chapter_ironclad = c7_aggregator.compute_is_ironclad(
            local_judgments,
            pairs=combined_pairs,
            baseline_excluded_segment_hashes=baseline_set,
        )
        if chapter_baseline_matched:
            # 章节标题命中 baseline → 整章节是模板,is_chapter_ironclad MUST = False
            # (即使 LLM 判 plagiarism 也不顶铁证;模板段被多家应标方共填合规)
            is_chapter_ironclad = False
        plag_count = sum(1 for v in local_judgments.values() if v == "plagiarism")

        # 本章节 samples(按 sim 降序前 N)
        samples_src = sorted(combined_pairs, key=lambda p: p.sim, reverse=True)
        samples = []
        for i, p in enumerate(samples_src[:_CHAPTER_SAMPLES_LIMIT]):
            # detect-tender-baseline §4:sample 段级 baseline 标记(同 §3)
            seg_baseline_source = "none"
            if baseline_set:
                seg_h = c7_aggregator._segment_hash_for(p.a_text)
                if seg_h in baseline_set:
                    seg_baseline_source = hash_to_source.get(seg_h, "none")
            samples.append(
                {
                    "a_idx": p.a_idx,
                    "b_idx": p.b_idx,
                    "a_text": p.a_text,
                    "b_text": p.b_text,
                    "sim": p.sim,
                    "label": (
                        local_judgments.get(i)
                        if i < len(local_pairs_in_selected)
                        else None
                    ),
                    "baseline_matched": seg_baseline_source != "none",
                    "baseline_source": seg_baseline_source,
                }
            )

        chapter_results.append(
            ChapterScoreResult(
                chapter_pair_idx=ch_idx,
                a_idx=cp.a_idx,
                b_idx=cp.b_idx,
                a_title=ca.title,
                b_title=cb.title,
                title_sim=cp.title_sim,
                aligned_by=cp.aligned_by,
                chapter_score=chapter_score,
                is_chapter_ironclad=is_chapter_ironclad,
                plagiarism_count=plag_count,
                para_pair_count=len(pairs),
                samples=samples,
                chapter_baseline_source=chapter_baseline_source,
                chapter_baseline_matched=chapter_baseline_matched,
            )
        )

    return chapter_results, selected_pairs, judgments, ai_meta


def aggregate_pair_level(
    chapter_results: list[ChapterScoreResult],
) -> tuple[float, bool]:
    """pair 级 score = max*0.6 + mean*0.4;is_ironclad = any(chapter ironclad)。"""
    if not chapter_results:
        return 0.0, False
    scores = [r.chapter_score for r in chapter_results]
    top = max(scores)
    avg = sum(scores) / len(scores)
    pair_score = top * 0.6 + avg * 0.4
    pair_score = max(0.0, min(100.0, pair_score))
    is_ironclad = any(r.is_chapter_ironclad for r in chapter_results)
    return round(pair_score, 2), is_ironclad


def aggregate_pc_baseline_source(
    chapter_results: list[ChapterScoreResult],
) -> str:
    """detect-tender-baseline §4:PC 顶级 baseline_source = 所有命中 source 的最强。

    取自:① 各章节 chapter_baseline_source(章节标题命中)② 各章节 sample 的
    baseline_source(段级命中)。优先级 tender > consensus > none。
    """
    pc_src = "none"
    for r in chapter_results:
        if (
            _BASELINE_SOURCE_PRIORITY[r.chapter_baseline_source]
            > _BASELINE_SOURCE_PRIORITY[pc_src]
        ):
            pc_src = r.chapter_baseline_source
        for s in r.samples:
            seg_src = s.get("baseline_source", "none")
            if (
                _BASELINE_SOURCE_PRIORITY[seg_src]
                > _BASELINE_SOURCE_PRIORITY[pc_src]
            ):
                pc_src = seg_src
    return pc_src


__all__ = [
    "score_all_chapter_pairs",
    "aggregate_pair_level",
    "aggregate_pc_baseline_source",
]
