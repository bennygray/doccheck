"""section_similarity Agent (C8 detect-agent-section-similarity)

章节级双轨算法:
1. 段落加载(复用 C7 segmenter)→ 2. 正则切章(chapter_parser)
3. 切分成功性判定 →(失败走 fallback 整文档降级)
4. 章节对齐(aligner)→ 5. 章节评分 + pair 汇总
   (scorer,复用 C7 tfidf/llm_judge/aggregator)
6. 写 PairComparison

preflight:
- 双方有同角色文档(C6 contract)+ 双方总字数 ≥ C7 TEXT_SIM_MIN_DOC_CHARS(300)
- 章节数检查不在 preflight,下放到 run() 内(切章失败走降级,不 skip)
"""

from __future__ import annotations

import logging
from decimal import Decimal

from app.models.pair_comparison import PairComparison
from app.services.detect import baseline_resolver
from app.services.detect.agents.section_sim_impl import (
    aligner,
    chapter_parser,
    fallback,
    raw_loader,
    scorer,
)
from app.services.detect.agents.section_sim_impl import (
    config as s_config,
)
from app.services.detect.agents.text_sim_impl import (
    config as c7_config,
)
from app.services.detect.agents.text_sim_impl import (
    segmenter,
)
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.errors import AgentSkippedError
from app.services.detect.registry import register_agent

logger = logging.getLogger(__name__)

# evidence_json.chapter_pairs 上限
_CHAPTER_PAIRS_LIMIT = 20


async def preflight(ctx: AgentContext) -> PreflightResult:
    if ctx.bidder_a is None or ctx.bidder_b is None or ctx.session is None:
        return PreflightResult("skip", "缺少可对比文档")

    shared = await segmenter.choose_shared_role(
        ctx.session, ctx.bidder_a.id, ctx.bidder_b.id
    )
    if not shared:
        return PreflightResult("skip", "缺少可对比文档")

    # 复用 C7 TEXT_SIM_MIN_DOC_CHARS 作为文档总字数下限
    min_chars = c7_config.min_doc_chars()
    seg_a = await segmenter.load_paragraphs_for_roles(
        ctx.session, ctx.bidder_a.id, shared
    )
    seg_b = await segmenter.load_paragraphs_for_roles(
        ctx.session, ctx.bidder_b.id, shared
    )
    if seg_a.total_chars < min_chars or seg_b.total_chars < min_chars:
        return PreflightResult("skip", "文档过短无法对比")
    return PreflightResult("ok")


@register_agent("section_similarity", "pair", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    """章节级双轨算法,替换 C6 的 dummy_pair_run。"""
    assert ctx.bidder_a is not None
    assert ctx.bidder_b is not None
    assert ctx.session is not None

    # 1) role 选择(复用 C7)+ 通过 segmenter 拿 doc_id / total_chars,
    #    但段落本身用 raw_loader(不合并,保留章节标题边界)
    shared = await segmenter.choose_shared_role(
        ctx.session, ctx.bidder_a.id, ctx.bidder_b.id
    )
    seg_a = await segmenter.load_paragraphs_for_roles(
        ctx.session, ctx.bidder_a.id, shared
    )
    seg_b = await segmenter.load_paragraphs_for_roles(
        ctx.session, ctx.bidder_b.id, shared
    )
    doc_role = seg_a.doc_role or seg_b.doc_role or "unknown"

    # C8 专用:不走 segmenter 合并,从 DB 直查 body raw 段落(保留章节标题独立)
    raw_paras_a = (
        await raw_loader.load_raw_body_paragraphs(ctx.session, seg_a.doc_id)
        if seg_a.doc_id else []
    )
    raw_paras_b = (
        await raw_loader.load_raw_body_paragraphs(ctx.session, seg_b.doc_id)
        if seg_b.doc_id else []
    )

    # detect-tender-baseline §4:加载 baseline 段级 hash 集合(章节标题 + 段级共用同 set)
    # fail-soft:任何异常返空 baseline,不阻塞 detector(L3 立场:基线缺失 ≠ 信号无效)
    try:
        baseline_segs = await baseline_resolver.get_excluded_segment_hashes_with_source(
            ctx.session, ctx.project_id, "section_similarity"
        )
        baseline_hash_to_source = baseline_segs.hash_to_source
        baseline_warnings = list(baseline_segs.warnings)
    except AgentSkippedError:
        # agent-skipped-error-guard:前置 re-raise,防 helper 抛 AgentSkippedError 被
        # 通用 except 吞成 failed 绕过 skipped 语义(harden-async-infra H2 同型)
        raise
    except Exception as exc:  # noqa: BLE001 - baseline 失败 fail-soft 不阻 detector
        logger.error(
            "section_similarity: baseline_resolver failed project=%s err=%s",
            ctx.project_id,
            exc,
        )
        baseline_hash_to_source = {}
        baseline_warnings = []

    # 2) 正则切章(基于 raw_paras,标题行独立不合并)
    min_chapter_chars_v = s_config.min_chapter_chars()
    chapters_a = chapter_parser.extract_chapters(raw_paras_a, min_chapter_chars_v)
    chapters_b = chapter_parser.extract_chapters(raw_paras_b, min_chapter_chars_v)

    # 3) 切分成功性判定 — 用 raw_paras 计数(更能反映真实段落量)
    min_chapters_v = s_config.min_chapters()
    total_paras = len(raw_paras_a) + len(raw_paras_b)
    degrade_reason: str | None = None
    if len(chapters_a) < min_chapters_v or len(chapters_b) < min_chapters_v:
        degrade_reason = (
            f"章节切分失败(chapters_a={len(chapters_a)}, "
            f"chapters_b={len(chapters_b)}, < {min_chapters_v})"
        )
    elif total_paras < 10:
        degrade_reason = f"段落总数不足({total_paras} < 10)"

    if degrade_reason is not None:
        score, is_ironclad, evidence = await fallback.run_doc_level_fallback(
            paragraphs_a=list(seg_a.paragraphs),
            paragraphs_b=list(seg_b.paragraphs),
            doc_role=doc_role,
            doc_id_a=seg_a.doc_id or 0,
            doc_id_b=seg_b.doc_id or 0,
            bidder_a_name=ctx.bidder_a.name,
            bidder_b_name=ctx.bidder_b.name,
            llm_provider=ctx.llm_provider,
            degrade_reason=degrade_reason,
            chapters_a_count=len(chapters_a),
            chapters_b_count=len(chapters_b),
            # detect-tender-baseline §4:fallback 路径同样接 baseline
            baseline_hash_to_source=baseline_hash_to_source,
            baseline_warnings=baseline_warnings,
        )
        summary = f"章节切分失败,已降级整文档粒度({degrade_reason})"
        if evidence.get("degraded"):
            summary += ";且 AI 研判暂不可用(LLM 降级)"
        return await _persist_and_return(
            ctx, score, is_ironclad, evidence, summary
        )

    # 4) 章节对齐
    threshold = s_config.title_align_threshold()
    chapter_pairs = aligner.align_chapters(chapters_a, chapters_b, threshold)

    # 5) 章节评分(detect-tender-baseline §4:透传 baseline 段级 hash 映射)
    (
        chapter_results,
        _all_pairs,
        all_judgments,
        ai_meta,
    ) = await scorer.score_all_chapter_pairs(
        chapters_a,
        chapters_b,
        chapter_pairs,
        ctx.llm_provider,
        ctx.bidder_a.name,
        ctx.bidder_b.name,
        doc_role,
        baseline_hash_to_source=baseline_hash_to_source,
    )

    pair_score, is_ironclad = scorer.aggregate_pair_level(chapter_results)
    pc_baseline_source = scorer.aggregate_pc_baseline_source(chapter_results)

    # 6) 构造 evidence_json
    evidence = _build_chapter_evidence(
        doc_role=doc_role,
        doc_id_a=seg_a.doc_id or 0,
        doc_id_b=seg_b.doc_id or 0,
        threshold=c7_config.pair_score_threshold(),
        chapters_a_count=len(chapters_a),
        chapters_b_count=len(chapters_b),
        chapter_pairs=chapter_pairs,
        chapter_results=chapter_results,
        all_judgments=all_judgments,
        ai_meta=ai_meta,
        # detect-tender-baseline §4:PC 顶级 baseline_source / warnings
        baseline_source=pc_baseline_source,
        baseline_warnings=baseline_warnings,
    )

    # summary
    degraded_llm = evidence.get("degraded", False)
    if degraded_llm:
        summary = "章节级对比完成,AI 研判暂不可用(LLM 降级,仅程序相似度)"
    elif is_ironclad:
        summary = (
            f"章节级命中:{evidence['pairs_plagiarism']} 段抄袭 / "
            f"{len(chapter_results)} 对齐章节"
        )
    else:
        summary = f"章节级对比完成,{len(chapter_results)} 对齐章节,未命中铁证"

    return await _persist_and_return(ctx, pair_score, is_ironclad, evidence, summary)


def _build_chapter_evidence(
    *,
    doc_role: str,
    doc_id_a: int,
    doc_id_b: int,
    threshold: float,
    chapters_a_count: int,
    chapters_b_count: int,
    chapter_pairs,
    chapter_results,
    all_judgments: dict,
    ai_meta: dict | None,
    baseline_source: str = "none",
    baseline_warnings: list[str] | None = None,
) -> dict:
    """章节模式 evidence_json(对齐 design D7 schema)。

    detect-tender-baseline §4 扩展:
    - 顶级 baseline_source(章节标题 + 段级命中取最强 source);老调用默认 "none"
    - 顶级 warnings(L3 警示数组);老调用默认 []
    - chapter_pairs[i] 加 chapter_baseline_source / chapter_baseline_matched
    - samples[i] 加 baseline_matched / baseline_source(scorer 已注入)
    """
    degraded = ai_meta is None
    plag = sum(1 for v in all_judgments.values() if v == "plagiarism")
    tmpl = sum(1 for v in all_judgments.values() if v == "template")
    gen = sum(1 for v in all_judgments.values() if v == "generic")
    if degraded:
        plag = 0
        tmpl = 0
        # 降级模式下 all_judgments 空,pairs_* 细分无意义,按"全 generic"填
        gen = sum(r.para_pair_count for r in chapter_results)

    # chapter_pairs 明细(按 chapter_score 降序,截 20)
    sorted_results = sorted(
        chapter_results, key=lambda r: r.chapter_score, reverse=True
    )[:_CHAPTER_PAIRS_LIMIT]
    chapter_pairs_ev = [
        {
            "a_idx": r.a_idx,
            "b_idx": r.b_idx,
            "a_title": r.a_title,
            "b_title": r.b_title,
            "title_sim": r.title_sim,
            "aligned_by": r.aligned_by,
            "chapter_score": r.chapter_score,
            "is_chapter_ironclad": r.is_chapter_ironclad,
            "plagiarism_count": r.plagiarism_count,
            # detect-tender-baseline §4 章节级 baseline 标记
            "chapter_baseline_source": r.chapter_baseline_source,
            "chapter_baseline_matched": r.chapter_baseline_matched,
        }
        for r in sorted_results
    ]

    # samples:跨章节按 sim 降序取 10 条(从各 chapter.samples 中取)
    all_samples = []
    for r in chapter_results:
        for s in r.samples:
            all_samples.append({**s, "chapter_idx": r.chapter_pair_idx})
    all_samples.sort(key=lambda s: s["sim"], reverse=True)
    samples = all_samples[:10]

    aligned_count = sum(1 for cp in chapter_pairs if cp.aligned_by == "title")
    index_count = sum(1 for cp in chapter_pairs if cp.aligned_by == "index")

    return {
        "algorithm": "tfidf_cosine_chapter_v1",
        "doc_role": doc_role,
        "doc_id_a": doc_id_a,
        "doc_id_b": doc_id_b,
        "threshold": threshold,
        "chapters_a_count": chapters_a_count,
        "chapters_b_count": chapters_b_count,
        "aligned_count": aligned_count,
        "index_fallback_count": index_count,
        "degraded_to_doc_level": False,
        "degrade_reason": None,
        "chapter_pairs": chapter_pairs_ev,
        "pairs_total": sum(r.para_pair_count for r in chapter_results),
        "pairs_plagiarism": plag,
        "pairs_template": tmpl,
        "pairs_generic": gen,
        "degraded": degraded,
        "ai_judgment": (
            {
                "overall": ai_meta.get("overall", ""),
                "confidence": ai_meta.get("confidence", ""),
            }
            if ai_meta is not None
            else None
        ),
        "samples": samples,
        # detect-tender-baseline §4:PC 顶级 baseline_source + warnings
        "baseline_source": baseline_source,
        "warnings": list(baseline_warnings or []),
    }


async def _persist_and_return(
    ctx: AgentContext,
    score: float,
    is_ironclad: bool,
    evidence: dict,
    summary: str,
) -> AgentRunResult:
    """写 PairComparison + 返 AgentRunResult。"""
    assert ctx.bidder_a is not None
    assert ctx.bidder_b is not None
    assert ctx.session is not None
    pc = PairComparison(
        project_id=ctx.project_id,
        version=ctx.version,
        bidder_a_id=ctx.bidder_a.id,
        bidder_b_id=ctx.bidder_b.id,
        dimension="section_similarity",
        score=Decimal(str(score)),
        is_ironclad=is_ironclad,
        evidence_json=evidence,
    )
    ctx.session.add(pc)
    await ctx.session.flush()
    return AgentRunResult(score=score, summary=summary[:500], evidence_json=evidence)
