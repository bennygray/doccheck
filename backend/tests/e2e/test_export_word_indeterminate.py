"""L2 - Word 模板对 indeterminate + 身份信息缺失的分支处理
(honest-detection-results 8.3)

覆盖 4 个 case:
(a) indeterminate 报告导出 — 上下文含"证据不足"中文 + is_indeterminate=True
(b) 含 insufficient bidder 的报告 — error_consistency 维度 evidence_summary 含降级文案
(c) 所有 bidder 身份完整 — error_consistency 维度不含降级文案
(d) low/medium/high 回归 — 原有上下文字段完整保留
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from app.models.analysis_report import AnalysisReport
from app.models.bidder import Bidder
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.services.export.generator import build_render_context


def _make_project() -> Project:
    p = Project(name="项目X", owner_id=1, status="completed")
    p.id = 1  # type: ignore[assignment]
    p.created_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    return p


def _make_ar(risk_level: str, llm_conclusion: str = "结论") -> AnalysisReport:
    ar = AnalysisReport(
        project_id=1,
        version=1,
        total_score=Decimal("0"),
        risk_level=risk_level,
        llm_conclusion=llm_conclusion,
    )
    ar.id = 100  # type: ignore[assignment]
    ar.created_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    ar.manual_review_status = None  # type: ignore[assignment]
    ar.manual_review_comment = None  # type: ignore[assignment]
    ar.reviewer_id = None  # type: ignore[assignment]
    ar.reviewed_at = None  # type: ignore[assignment]
    return ar


def _make_bidder(identity_info: Any) -> Bidder:
    b = Bidder(
        name="B", project_id=1, parse_status="identified", identity_info=identity_info
    )
    b.id = 10  # type: ignore[assignment]
    return b


# ---- case (a) indeterminate 报告 ----


def test_indeterminate_context_fields() -> None:
    ctx = build_render_context(
        project=_make_project(),
        ar=_make_ar(
            "indeterminate",
            "证据不足,无法判定围标风险(有效信号维度全部为零)",
        ),
        oa_rows=[],
        pc_rows=[],
        bidders=[],
    )
    assert ctx["report"]["risk_level"] == "indeterminate"
    assert ctx["report"]["risk_level_cn"] == "证据不足"
    assert ctx["report"]["is_indeterminate"] is True
    assert "证据不足" in ctx["report"]["llm_conclusion"]


# ---- case (b) 含 insufficient bidder ----


def test_insufficient_bidder_triggers_error_consistency_degraded_note() -> None:
    ctx = build_render_context(
        project=_make_project(),
        ar=_make_ar("medium"),
        oa_rows=[],
        pc_rows=[],
        bidders=[_make_bidder(None)],  # identity_info=None → insufficient
    )
    assert ctx["has_insufficient_identity"] is True
    # error_consistency 维度的 evidence_summary 应含降级文案
    ec_dim = next(
        d for d in ctx["dimensions"] if d["name"] == "error_consistency"
    )
    assert "身份信息缺失情况下已降级判定" in ec_dim["evidence_summary"]


# ---- case (c) 身份完整不追加降级注 ----


def test_sufficient_bidder_error_consistency_no_degraded_note() -> None:
    ctx = build_render_context(
        project=_make_project(),
        ar=_make_ar("low"),
        oa_rows=[],
        pc_rows=[],
        bidders=[_make_bidder({"company_full_name": "某某有限公司"})],
    )
    assert ctx["has_insufficient_identity"] is False
    ec_dim = next(
        d for d in ctx["dimensions"] if d["name"] == "error_consistency"
    )
    assert "身份信息缺失情况下已降级判定" not in (
        ec_dim.get("evidence_summary") or ""
    )


# ---- case (d) low/medium/high 回归 ----


@pytest.mark.parametrize("level,cn", [
    ("low", "低风险"),
    ("medium", "中风险"),
    ("high", "高风险"),
])
def test_low_medium_high_regression(level: str, cn: str) -> None:
    ctx = build_render_context(
        project=_make_project(),
        ar=_make_ar(level, "经公式 + LLM 研判"),
        oa_rows=[],
        pc_rows=[],
        bidders=[_make_bidder({"company_full_name": "X"})],
    )
    assert ctx["report"]["risk_level"] == level
    assert ctx["report"]["risk_level_cn"] == cn
    assert ctx["report"]["is_indeterminate"] is False
    assert ctx["report"]["llm_conclusion"] == "经公式 + LLM 研判"
    # error_consistency 不降级(身份完整)
    ec_dim = next(
        d for d in ctx["dimensions"] if d["name"] == "error_consistency"
    )
    assert "身份信息缺失" not in (ec_dim.get("evidence_summary") or "")
