"""TypedDict 契约 (C10 detect-agents-metadata)

仅内部类型契约,不做序列化;evidence_json 最终存 dict 到 JSONB。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict


class MetadataRecord(TypedDict):
    """单文档元数据快照(归一化 + 原值并存)。"""

    bid_document_id: int
    bidder_id: int
    doc_name: str
    # 归一化后字段(None 视为缺失)
    author_norm: str | None
    last_saved_by_norm: str | None
    company_norm: str | None
    template_norm: str | None
    app_name: str | None
    app_version: str | None
    # 时间字段(不归一化)
    doc_created_at: datetime | None
    doc_modified_at: datetime | None
    # 原值(展示用)
    author_raw: str | None
    last_saved_by_raw: str | None
    company_raw: str | None
    template_raw: str | None


class ClusterHit(TypedDict, total=False):
    """通用命中条目。author/machine 用。"""

    field: str
    value: Any
    normalized: str | None
    doc_ids_a: list[int]
    doc_ids_b: list[int]


class TimeCluster(TypedDict, total=False):
    """time Agent 的命中条目。"""

    dimension: str  # "modified_at_cluster" | "created_at_match"
    window_min: int
    doc_ids_a: list[int]
    doc_ids_b: list[int]
    times: list[str]  # ISO-8601 字符串


class AuthorDimResult(TypedDict):
    score: float | None
    reason: str | None
    sub_scores: dict[str, float]
    hits: list[ClusterHit]


class TimeDimResult(TypedDict):
    score: float | None
    reason: str | None
    sub_scores: dict[str, float]
    hits: list[TimeCluster]


class MachineDimResult(TypedDict):
    score: float | None
    reason: str | None
    hits: list[ClusterHit]


__all__ = [
    "MetadataRecord",
    "ClusterHit",
    "TimeCluster",
    "AuthorDimResult",
    "TimeDimResult",
    "MachineDimResult",
]
