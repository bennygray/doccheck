"""style 数据契约 (C13)"""

from __future__ import annotations

from typing import TypedDict


class StyleFeatureBrief(TypedDict, total=False):
    """L-8 Stage1 输出:每 bidder 一份风格摘要。"""

    bidder_id: int
    用词偏好: str
    句式特点: str
    标点习惯: str
    段落组织: str
    low_confidence: bool


class ConsistentGroup(TypedDict):
    bidder_ids: list[int]
    consistency_score: float
    typical_features: str


class GlobalComparison(TypedDict, total=False):
    consistent_groups: list[ConsistentGroup]


class DetectionResult(TypedDict, total=False):
    style_features_per_bidder: dict[str, StyleFeatureBrief]
    global_comparison: GlobalComparison
    grouping_strategy: str  # "single" | "grouped"
    group_count: int
    insufficient_sample_bidders: list[int]


__all__ = [
    "StyleFeatureBrief",
    "ConsistentGroup",
    "GlobalComparison",
    "DetectionResult",
]
