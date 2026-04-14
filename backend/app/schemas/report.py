"""Report API schemas (C6 detect-framework)。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


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
    """GET /reports/{version} 响应(C6 骨架;详细 Tab 留 C14)。"""

    version: int
    total_score: float
    risk_level: str  # high|medium|low
    llm_conclusion: str  # C6 恒 ""
    created_at: datetime
    dimensions: list[ReportDimension]
