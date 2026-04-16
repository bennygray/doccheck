"""text_similarity Agent (C7 detect-agent-text-similarity)

双轨分工(design D1-D7):
1. 本地 TF-IDF + cosine 筛段落对(始终跑,CPU 密集走 ProcessPoolExecutor)
2. LLM 定性每对 plagiarism / template / generic(按 §10.8 L-4)
3. 失败降级:全部按 generic 权重 0.3,is_ironclad=False,summary="AI 研判暂不可用"

preflight:
- "同角色文档存在"(C6 锁定 contract) +
- 超短文档 skip(任一侧 total_chars < MIN_DOC_CHARS,默认 300)
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from app.models.pair_comparison import PairComparison
from app.services.detect.agents.text_sim_impl import (
    aggregator,
    config,
    llm_judge,
    segmenter,
    tfidf,
)
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.engine import get_cpu_executor
from app.services.detect.registry import register_agent

logger = logging.getLogger(__name__)

_DEGRADED_SUMMARY = "AI 研判暂不可用,仅展示程序相似度(降级)"


async def preflight(ctx: AgentContext) -> PreflightResult:
    if ctx.bidder_a is None or ctx.bidder_b is None or ctx.session is None:
        return PreflightResult("skip", "缺少可对比文档")

    shared = await segmenter.choose_shared_role(
        ctx.session, ctx.bidder_a.id, ctx.bidder_b.id
    )
    if not shared:
        return PreflightResult("skip", "缺少可对比文档")

    # 字数检查(design D1):任一侧选中文档 total_chars < MIN_DOC_CHARS → skip
    min_chars = config.min_doc_chars()
    seg_a = await segmenter.load_paragraphs_for_roles(
        ctx.session, ctx.bidder_a.id, shared
    )
    seg_b = await segmenter.load_paragraphs_for_roles(
        ctx.session, ctx.bidder_b.id, shared
    )
    if seg_a.total_chars < min_chars or seg_b.total_chars < min_chars:
        return PreflightResult("skip", "文档过短无法对比")
    return PreflightResult("ok")


@register_agent("text_similarity", "pair", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    """真实双轨算法,替换 C6 的 dummy_pair_run。"""
    assert ctx.bidder_a is not None
    assert ctx.bidder_b is not None
    assert ctx.session is not None

    # 1) 再次加载段落(preflight 的结果不跨函数传,engine 只传 ctx,多一次查但成本低)
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

    # 2) CPU 密集:TF-IDF 向量化 + cosine 矩阵 → 超阈值段落对
    threshold = config.pair_score_threshold()
    max_pairs = config.max_pairs_to_llm()
    loop = asyncio.get_running_loop()
    pairs = await loop.run_in_executor(
        get_cpu_executor(),
        tfidf.compute_pair_similarity,
        seg_a.paragraphs,
        seg_b.paragraphs,
        threshold,
        max_pairs,
    )

    # 3) LLM 定性判定(无超阈值段对 → 跳 LLM,judgments 空但不算降级)
    if pairs:
        judgments, ai_meta = await llm_judge.call_llm_judge(
            ctx.llm_provider,
            ctx.bidder_a.name,
            ctx.bidder_b.name,
            doc_role,
            pairs,
        )
    else:
        judgments, ai_meta = {}, {"overall": "未检出超阈值段落对", "confidence": "high"}

    # 4) 汇总 score + is_ironclad
    score = aggregator.aggregate_pair_score(pairs, judgments)
    is_ironclad = aggregator.compute_is_ironclad(judgments)

    # 5) evidence_json
    evidence = aggregator.build_evidence_json(
        doc_role=doc_role,
        doc_id_a=seg_a.doc_id or 0,
        doc_id_b=seg_b.doc_id or 0,
        threshold=threshold,
        pairs=pairs,
        judgments=judgments,
        ai_meta=ai_meta,
    )

    # 6) 写 PairComparison 行
    pc = PairComparison(
        project_id=ctx.project_id,
        version=ctx.version,
        bidder_a_id=ctx.bidder_a.id,
        bidder_b_id=ctx.bidder_b.id,
        dimension="text_similarity",
        score=Decimal(str(score)),
        is_ironclad=is_ironclad,
        evidence_json=evidence,
    )
    ctx.session.add(pc)
    await ctx.session.flush()

    # 7) 返 AgentRunResult(summary 降级时固定文案)
    if evidence["degraded"]:
        summary = _DEGRADED_SUMMARY
    elif pairs and ai_meta is not None:
        summary = (ai_meta.get("overall") or f"发现 {len(pairs)} 组高相似段落对")[:500]
    else:
        summary = "未检出超阈值段落对"

    return AgentRunResult(score=score, summary=summary, evidence_json=evidence)
