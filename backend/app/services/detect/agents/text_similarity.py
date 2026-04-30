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

import logging
from decimal import Decimal

from app.models.pair_comparison import PairComparison
from app.services.detect import baseline_resolver
from app.services.detect.errors import AgentSkippedError
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
    # harden-async-infra F1:per-task 子进程隔离,坏 docx 段错误只影响本 agent
    threshold = config.pair_score_threshold()
    max_pairs = config.max_pairs_to_llm()
    from app.core.config import settings
    from app.services.detect.agents._subprocess import run_isolated

    # text-sim-exact-match-bypass D3: hash 旁路在 compute_pair_similarity 内嵌实施
    # (raw body 段 hash 命中已尝试但触发 LLM 单维度 timeout,回退到合并段路径;
    #  47 字 < MIN_PARAGRAPH_CHARS=50 被合并稀释属已知短段限制,留 v2 ngram 路径处理)
    pairs = await run_isolated(
        tfidf.compute_pair_similarity,
        seg_a.paragraphs,
        seg_b.paragraphs,
        threshold,
        max_pairs,
        timeout=settings.agent_subprocess_timeout,
    )

    # 3) LLM 定性判定(text-sim-exact-match-bypass: hash 命中段不送 LLM,只送 cosine 候选)
    cosine_pairs = [p for p in pairs if p.match_kind != "exact_match"]
    if cosine_pairs:
        cosine_judgments, ai_meta = await llm_judge.call_llm_judge(
            ctx.llm_provider,
            ctx.bidder_a.name,
            ctx.bidder_b.name,
            doc_role,
            cosine_pairs,
        )
    else:
        cosine_judgments, ai_meta = (
            {},
            {"overall": "未检出超阈值段落对", "confidence": "high"},
        )

    # 把 cosine_pairs idx 内的 judgments 映射回 pairs 全局 idx(hash 段在前面占据 [0..exact_n))
    exact_n = len(pairs) - len(cosine_pairs)
    judgments: dict[int, str] = {
        i + exact_n: v for i, v in cosine_judgments.items()
    }

    # detect-tender-baseline §3:加载 baseline 段级 hash 集合(L1 tender / L2 共识 / L3 警示)
    # fail-soft:任何异常返空 baseline,不阻塞 detector(L3 立场:基线缺失 ≠ 信号无效)
    try:
        baseline_segs = await baseline_resolver.get_excluded_segment_hashes_with_source(
            ctx.session, ctx.project_id, "text_similarity"
        )
        baseline_hash_to_source = baseline_segs.hash_to_source
        baseline_excluded = set(baseline_segs.hash_to_source.keys())
        baseline_warnings = list(baseline_segs.warnings)
    except AgentSkippedError:
        # agent-skipped-error-guard:前置 re-raise,防未来 helper 抛 AgentSkippedError 被
        # 通用 except 吞成 failed 绕过 skipped 语义(harden-async-infra H2 同型隐患)
        raise
    except Exception as exc:  # noqa: BLE001 - baseline 失败 fail-soft 不阻 detector
        logger.error(
            "text_similarity: baseline_resolver failed project=%s err=%s",
            ctx.project_id,
            exc,
        )
        baseline_hash_to_source = {}
        baseline_excluded = set()
        baseline_warnings = []

    # 4) 汇总 score + is_ironclad(text-sim-exact-match-bypass: ironclad 加 ≥50 字 exact_match 门槛;
    #    detect-tender-baseline §3:baseline 命中段跳过 ironclad 触发,段仍计入 score)
    degraded = ai_meta is None
    score = aggregator.aggregate_pair_score(pairs, judgments)
    is_ironclad = aggregator.compute_is_ironclad(
        judgments,
        pairs=pairs,
        degraded=degraded,
        baseline_excluded_segment_hashes=baseline_excluded,
    )

    # 5) evidence_json — text-sim-exact-match-bypass UI 修正:
    # pairs 的 a_idx/b_idx 是 merged 段索引,前端 TextComparePage 用 DocumentText.paragraph_index
    # 做高亮映射。在写 evidence 前用 segmenter 暴露的 anchor 把 merged idx 转回 raw paragraph_index,
    # 否则 leftMatchMap.get(p.paragraph_index) 永远查不到 → UI 不高亮。
    a_anchors = seg_a.merged_anchor_paragraph_index
    b_anchors = seg_b.merged_anchor_paragraph_index
    pairs_for_evidence = []
    from app.services.detect.agents.text_sim_impl.models import ParaPair
    for p in pairs:
        a_idx_raw = a_anchors[p.a_idx] if 0 <= p.a_idx < len(a_anchors) else p.a_idx
        b_idx_raw = b_anchors[p.b_idx] if 0 <= p.b_idx < len(b_anchors) else p.b_idx
        pairs_for_evidence.append(
            ParaPair(
                a_idx=a_idx_raw,
                b_idx=b_idx_raw,
                a_text=p.a_text,
                b_text=p.b_text,
                sim=p.sim,
                match_kind=p.match_kind,
            )
        )
    evidence = aggregator.build_evidence_json(
        doc_role=doc_role,
        doc_id_a=seg_a.doc_id or 0,
        doc_id_b=seg_b.doc_id or 0,
        threshold=threshold,
        pairs=pairs_for_evidence,
        judgments=judgments,
        ai_meta=ai_meta,
        # detect-tender-baseline §3:段级 baseline_matched / baseline_source 写入
        baseline_hash_to_source=baseline_hash_to_source,
        baseline_warnings=baseline_warnings,
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
