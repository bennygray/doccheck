"""Report API schemas (C6 detect-framework + C15 report-export)。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# honest-detection-results:risk_level 枚举扩展
RiskLevelLiteral = Literal["high", "medium", "low", "indeterminate"]


class ReportDimensionStatusCounts(BaseModel):
    succeeded: int = 0
    failed: int = 0
    timeout: int = 0
    skipped: int = 0


class ReportDimension(BaseModel):
    dimension: str
    best_score: float
    is_ironclad: bool
    status_counts: ReportDimensionStatusCounts = Field(
        default_factory=ReportDimensionStatusCounts
    )
    summaries: list[str] = Field(default_factory=list)


class ReportResponse(BaseModel):
    """GET /reports/{version} 响应(C6 骨架 + C15 扩 manual_review_*)。"""

    version: int
    total_score: float
    risk_level: RiskLevelLiteral  # honest-detection-results: 新增 indeterminate
    llm_conclusion: str
    created_at: datetime
    dimensions: list[ReportDimension]
    # C15 新增:整报告级人工复核字段(未复核时 null)
    manual_review_status: str | None = None
    manual_review_comment: str | None = None
    reviewer_id: int | None = None
    reviewed_at: datetime | None = None
    # CH-2 detect-template-exclusion: 模板簇识别可观测性
    template_cluster_detected: bool = False
    template_cluster_adjusted_scores: dict[str, Any] | None = None


# ================================================================= C15


class ReportDimensionDetail(BaseModel):
    """GET /reports/{version}/dimensions 单行。"""

    dimension: str
    best_score: float
    is_ironclad: bool
    evidence_summary: str
    manual_review_json: dict[str, Any] | None = None


class ReportDimensionsResponse(BaseModel):
    dimensions: list[ReportDimensionDetail]


class PairComparisonItem(BaseModel):
    id: int
    dimension: str
    bidder_a_id: int
    bidder_b_id: int
    score: float
    is_ironclad: bool
    evidence_summary: str | None = None


class PairsResponse(BaseModel):
    items: list[PairComparisonItem]


class LogEntry(BaseModel):
    source: str  # 'agent_task' | 'audit_log'
    created_at: datetime
    payload: dict[str, Any]


class LogsResponse(BaseModel):
    items: list[LogEntry]
