"""structure_similarity Agent (C9 detect-agent-structure-similarity)

三维度纯程序化结构相似度:
1. 目录结构:docx 两侧章节标题序列 LCS(复用 C8 chapter_parser)
2. 字段结构:xlsx 列头 + bitmask + 合并单元格 Jaccard
3. 表单填充模式:xlsx cell type pattern Jaccard

preflight:
- 双方有同角色文档(C6 contract)+ 至少一侧有 docx 或 xlsx(C9)
- 维度级提取失败下放到 run() 内部各自判定,不做 Agent 级 skip
- 3 维度全 None → run 级 skip(score=0.0 + participating_dimensions=[])
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from app.models.pair_comparison import PairComparison
from app.services.detect.agents._preflight_helpers import (
    bidders_share_any_role,
    bidders_share_role_with_ext,
)
from app.services.detect.agents.structure_sim_impl import (
    config,
    field_sig,
    fill_pattern,
    loaders,
    scorer,
    title_lcs,
)
from app.services.detect.context import (
    AgentContext,
    AgentRunResult,
    PreflightResult,
)
from app.services.detect.registry import register_agent

logger = logging.getLogger(__name__)


async def preflight(ctx: AgentContext) -> PreflightResult:
    if ctx.bidder_a is None or ctx.bidder_b is None or ctx.session is None:
        return PreflightResult("skip", "缺少可对比文档")
    # C6 原约束:有共享 file_role
    if not await bidders_share_any_role(
        ctx.session, ctx.bidder_a.id, ctx.bidder_b.id
    ):
        return PreflightResult("skip", "缺少可对比文档")
    # C9 追加:至少一侧有共享 docx 或 xlsx
    has_docx = await bidders_share_role_with_ext(
        ctx.session, ctx.bidder_a.id, ctx.bidder_b.id, {".docx"}
    )
    has_xlsx = await bidders_share_role_with_ext(
        ctx.session, ctx.bidder_a.id, ctx.bidder_b.id, {".xlsx"}
    )
    if not has_docx and not has_xlsx:
        return PreflightResult("skip", "结构缺失")
    return PreflightResult("ok")


@register_agent("structure_similarity", "pair", preflight)
async def run(ctx: AgentContext) -> AgentRunResult:
    """替换 C6 dummy,三维度并行计算 + 聚合。"""
    assert ctx.bidder_a is not None
    assert ctx.bidder_b is not None
    assert ctx.session is not None

    # 1) 并行加载:docx pair(目录维度用)+ xlsx pair(字段/填充维度用)
    docx_pair_task = loaders.load_docx_titles_pair(
        ctx.session, ctx.bidder_a.id, ctx.bidder_b.id
    )
    xlsx_pair_task = loaders.load_xlsx_sheets_pair(
        ctx.session, ctx.bidder_a.id, ctx.bidder_b.id
    )
    docx_pair, xlsx_pair = await asyncio.gather(
        docx_pair_task, xlsx_pair_task
    )

    # 2) 三维度并行计算
    dir_task: asyncio.Future | None = None
    if docx_pair is not None:
        dir_task = asyncio.ensure_future(
            title_lcs.compute_directory_similarity(
                docx_pair.titles_a,
                docx_pair.titles_b,
                doc_id_a=docx_pair.doc_id_a,
                doc_id_b=docx_pair.doc_id_b,
            )
        )

    # field/fill 是同步的(Jaccard 快),不走 executor
    dir_result = await dir_task if dir_task is not None else None
    field_result = (
        field_sig.compute_field_similarity(
            xlsx_pair.sheets_a, xlsx_pair.sheets_b
        )
        if xlsx_pair is not None
        else None
    )
    fill_result = (
        fill_pattern.compute_fill_similarity(
            xlsx_pair.sheets_a, xlsx_pair.sheets_b
        )
        if xlsx_pair is not None
        else None
    )

    # 3) 聚合 + evidence
    agg = scorer.aggregate_structure_score(
        dir_result, field_result, fill_result, config.weights()
    )

    # 决定维度 skip reason
    dir_skip = _dir_skip_reason(docx_pair, dir_result)
    field_skip = _xlsx_skip_reason(xlsx_pair, field_result)
    fill_skip = _xlsx_skip_reason(xlsx_pair, fill_result)

    # doc_role / doc_ids:目录+xlsx 的角色可能不同,evidence 里各自保留
    doc_role = _merge_doc_role(docx_pair, xlsx_pair)
    doc_id_a = _collect_doc_ids(docx_pair, xlsx_pair, side="a")
    doc_id_b = _collect_doc_ids(docx_pair, xlsx_pair, side="b")

    evidence = scorer.build_evidence_json(
        dir_result,
        field_result,
        fill_result,
        agg,
        doc_role=doc_role,
        doc_id_a=doc_id_a,
        doc_id_b=doc_id_b,
        dir_skip_reason=dir_skip,
        field_skip_reason=field_skip,
        fill_skip_reason=fill_skip,
    )

    # 4) 决定最终 score + summary
    if agg.score is None:
        # run 级 skip:全维度 None
        summary = _build_skip_summary(dir_skip, field_skip, fill_skip)
        return await _persist_and_return(
            ctx, 0.0, False, evidence, summary
        )

    summary = _build_summary(agg, dir_result, field_result, fill_result)
    return await _persist_and_return(
        ctx, agg.score, agg.is_ironclad, evidence, summary
    )


def _dir_skip_reason(docx_pair, dir_result) -> str | None:
    if dir_result is not None:
        return None
    if docx_pair is None:
        return "docx_shared_role_missing"
    # docx 存在但章节数不足
    return "chapters_below_min"


def _xlsx_skip_reason(xlsx_pair, dim_result) -> str | None:
    if dim_result is not None:
        return None
    if xlsx_pair is None:
        return "xlsx_sheet_missing"
    # xlsx 存在但 min_rows 过滤后无 sheet 参与
    return "sheet_rows_below_min"


def _merge_doc_role(docx_pair, xlsx_pair) -> str:
    roles = [p.doc_role for p in (docx_pair, xlsx_pair) if p is not None]
    if not roles:
        return "unknown"
    return roles[0] if len(set(roles)) == 1 else "+".join(sorted(set(roles)))


def _collect_doc_ids(docx_pair, xlsx_pair, side: str) -> list[int]:
    ids: list[int] = []
    for p in (docx_pair, xlsx_pair):
        if p is None:
            continue
        v = p.doc_id_a if side == "a" else p.doc_id_b
        if v not in ids:
            ids.append(v)
    return ids


def _build_summary(agg, dir_r, field_r, fill_r) -> str:
    parts: list[str] = []
    if dir_r is not None:
        parts.append(
            f"目录 LCS={dir_r.lcs_length}/"
            f"{dir_r.titles_a_count}+{dir_r.titles_b_count}"
        )
    if field_r is not None:
        parts.append(f"字段={field_r.score:.2f}")
    if fill_r is not None:
        parts.append(f"填充={fill_r.score:.2f}")
    body = "、".join(parts)
    if agg.is_ironclad:
        return f"结构铁证命中({body}),综合 score={agg.score}"
    return f"结构相似度 score={agg.score}({body})"


def _build_skip_summary(
    dir_skip: str | None,
    field_skip: str | None,
    fill_skip: str | None,
) -> str:
    reasons = [r for r in (dir_skip, field_skip, fill_skip) if r]
    if reasons:
        return f"结构缺失:{','.join(sorted(set(reasons)))}"
    return "结构缺失"


async def _persist_and_return(
    ctx: AgentContext,
    score: float,
    is_ironclad: bool,
    evidence: dict,
    summary: str,
) -> AgentRunResult:
    assert ctx.bidder_a is not None
    assert ctx.bidder_b is not None
    assert ctx.session is not None
    pc = PairComparison(
        project_id=ctx.project_id,
        version=ctx.version,
        bidder_a_id=ctx.bidder_a.id,
        bidder_b_id=ctx.bidder_b.id,
        dimension="structure_similarity",
        score=Decimal(str(score)),
        is_ironclad=is_ironclad,
        evidence_json=evidence,
    )
    ctx.session.add(pc)
    await ctx.session.flush()
    return AgentRunResult(
        score=score, summary=summary[:500], evidence_json=evidence
    )
