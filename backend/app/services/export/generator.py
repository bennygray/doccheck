"""render_context 装配 + docxtpl 渲染 (C15 report-export, D6)

纯函数 build_render_context(ar, oa_rows, pc_rows, review, project, top_k=5)
返回 dict 供 docxtpl 渲染。不做 IO。

render_to_file(template_path, context, output_path) 真正执行渲染;
异常向上抛(由 worker 捕获决定回退 / FAILED)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from docxtpl import DocxTemplate

from app.models.analysis_report import AnalysisReport
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.services.detect.judge import DIMENSION_WEIGHTS


def _summary_of_evidence(evidence_json: dict | None) -> str:
    if not evidence_json:
        return ""
    for key in ("summary", "reason", "conclusion"):
        val = evidence_json.get(key)
        if isinstance(val, str) and val:
            return val
    try:
        return json.dumps(evidence_json, ensure_ascii=False)[:200]
    except (TypeError, ValueError):
        return ""


def _aggregate_dimensions(
    oa_rows: Iterable[OverallAnalysis], pc_rows: Iterable[PairComparison]
) -> list[dict[str, Any]]:
    """按 DIMENSION_WEIGHTS 顺序聚合 11 维度(含 best_score / is_ironclad / evidence_summary)。"""
    best_score: dict[str, float] = {}
    iron: dict[str, bool] = {}
    best_ev: dict[str, dict | None] = {}

    for oa in oa_rows:
        score = float(oa.score) if oa.score is not None else 0.0
        if score > best_score.get(oa.dimension, -1.0):
            best_score[oa.dimension] = score
            best_ev[oa.dimension] = oa.evidence_json
        if oa.evidence_json and oa.evidence_json.get("has_iron_evidence") is True:
            iron[oa.dimension] = True

    for pc in pc_rows:
        score = float(pc.score) if pc.score is not None else 0.0
        if score > best_score.get(pc.dimension, -1.0):
            best_score[pc.dimension] = score
            best_ev[pc.dimension] = pc.evidence_json
        if pc.is_ironclad:
            iron[pc.dimension] = True

    return [
        {
            "name": dim,
            "best_score": best_score.get(dim, 0.0),
            "is_ironclad": iron.get(dim, False),
            "evidence_summary": _summary_of_evidence(best_ev.get(dim)),
        }
        for dim in DIMENSION_WEIGHTS.keys()
    ]


def _top_pairs(
    pc_rows: Iterable[PairComparison], top_k: int = 5
) -> list[dict[str, Any]]:
    """按 score DESC 取 top-k;铁证 pair 优先(排序键:(is_ironclad 降序, score 降序))。"""
    sorted_pcs = sorted(
        pc_rows,
        key=lambda p: (
            1 if p.is_ironclad else 0,
            float(p.score) if p.score is not None else 0.0,
        ),
        reverse=True,
    )
    return [
        {
            "bidder_a": pc.bidder_a_id,
            "bidder_b": pc.bidder_b_id,
            "dimension": pc.dimension,
            "score": float(pc.score) if pc.score is not None else 0.0,
            "is_ironclad": bool(pc.is_ironclad),
            "summary": _summary_of_evidence(pc.evidence_json),
        }
        for pc in sorted_pcs[:top_k]
    ]


def build_render_context(
    *,
    project: Project,
    ar: AnalysisReport,
    oa_rows: Iterable[OverallAnalysis],
    pc_rows: Iterable[PairComparison],
    top_k: int = 5,
) -> dict[str, Any]:
    """装配 docxtpl 渲染上下文。design D6 schema。"""
    # 物化成 list(支持多次迭代)
    oa_list = list(oa_rows)
    pc_list = list(pc_rows)

    review_section: dict[str, Any] | None = None
    if ar.manual_review_status is not None:
        review_section = {
            "status": ar.manual_review_status,
            "comment": ar.manual_review_comment or "",
            "reviewer_id": ar.reviewer_id,
            "reviewed_at": ar.reviewed_at.isoformat() if ar.reviewed_at else "",
        }

    return {
        "project": {
            "name": project.name,
            "submitted_at": project.created_at.isoformat()
            if project.created_at
            else "",
        },
        "report": {
            "version": ar.version,
            "total_score": float(ar.total_score),
            "risk_level": ar.risk_level,
            "llm_conclusion": ar.llm_conclusion or "",
        },
        "dimensions": _aggregate_dimensions(oa_list, pc_list),
        "top_pairs": _top_pairs(pc_list, top_k=top_k),
        "review": review_section,
    }


def render_to_file(
    template_path: Path, context: dict[str, Any], output_path: Path
) -> int:
    """渲染 docx 并落盘。返回文件大小字节数。异常向上抛。"""
    doc = DocxTemplate(str(template_path))
    doc.render(context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return output_path.stat().st_size


__all__ = ["build_render_context", "render_to_file"]
