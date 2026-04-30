"""降级分支 - 章节切分失败时走整文档粒度 (C8 design D5, A1 独立降级)

不调用 text_similarity.run(),避免跨 Agent 耦合;直接 import text_sim_impl
模块内各函数重新走一遍整文档路径。dimension 仍写 section_similarity。
"""

from __future__ import annotations

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
from app.services.llm.base import LLMProvider


async def run_doc_level_fallback(
    paragraphs_a: list[str],
    paragraphs_b: list[str],
    doc_role: str,
    doc_id_a: int,
    doc_id_b: int,
    bidder_a_name: str,
    bidder_b_name: str,
    llm_provider: LLMProvider | None,
    degrade_reason: str,
    chapters_a_count: int,
    chapters_b_count: int,
    *,
    baseline_hash_to_source: dict[str, str] | None = None,
    baseline_warnings: list[str] | None = None,
) -> tuple[float, bool, dict]:
    """走整文档 TF-IDF + LLM 路径,返 (score, is_ironclad, evidence_json)。

    evidence_json 的 algorithm / degraded_to_doc_level / degrade_reason / chapter_* 字段
    标记本次是"章节切分失败降级"。

    detect-tender-baseline §4:fallback 路径与主路径对齐 — 段级 baseline 命中跳过
    ironclad + samples 段级 baseline_matched / baseline_source + 顶级 baseline_source
    / warnings 同 §3 c7 aggregator 内部处理。
    """
    hash_to_source = baseline_hash_to_source or {}
    baseline_set = set(hash_to_source.keys())
    threshold = c7_config.pair_score_threshold()
    max_pairs = c7_config.max_pairs_to_llm()

    # harden-async-infra F1:per-task 子进程隔离
    from app.core.config import settings
    from app.services.detect.agents._subprocess import run_isolated

    para_pairs = await run_isolated(
        c7_tfidf.compute_pair_similarity,
        paragraphs_a,
        paragraphs_b,
        threshold,
        max_pairs,
        timeout=settings.agent_subprocess_timeout,
    )

    if para_pairs:
        judgments, ai_meta = await c7_llm_judge.call_llm_judge(
            llm_provider,
            bidder_a_name,
            bidder_b_name,
            doc_role,
            para_pairs,
        )
    else:
        judgments, ai_meta = {}, {"overall": "未检出超阈值段落对", "confidence": "high"}

    score = c7_aggregator.aggregate_pair_score(para_pairs, judgments)
    is_ironclad = c7_aggregator.compute_is_ironclad(
        judgments,
        pairs=para_pairs,
        baseline_excluded_segment_hashes=baseline_set,
    )

    # 复用 C7 的 build_evidence_json 起手,再追加章节层专属字段
    base_evidence = c7_aggregator.build_evidence_json(
        doc_role=doc_role,
        doc_id_a=doc_id_a,
        doc_id_b=doc_id_b,
        threshold=threshold,
        pairs=para_pairs,
        judgments=judgments,
        ai_meta=ai_meta,
        baseline_hash_to_source=hash_to_source,
        baseline_warnings=baseline_warnings,
    )
    # 覆盖 algorithm 标签
    base_evidence["algorithm"] = "tfidf_cosine_fallback_to_doc"
    # 章节层专属字段
    base_evidence["chapters_a_count"] = chapters_a_count
    base_evidence["chapters_b_count"] = chapters_b_count
    base_evidence["aligned_count"] = 0
    base_evidence["index_fallback_count"] = 0
    base_evidence["degraded_to_doc_level"] = True
    base_evidence["degrade_reason"] = degrade_reason
    base_evidence["chapter_pairs"] = []

    return score, is_ironclad, base_evidence


__all__ = ["run_doc_level_fallback"]
