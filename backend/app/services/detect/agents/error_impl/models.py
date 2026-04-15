"""error_consistency 数据契约 (C13)

4 个 TypedDict:SuspiciousSegment / KeywordHit / LLMJudgment / DetectionResult。
"""

from __future__ import annotations

from typing import TypedDict


class KeywordHit(TypedDict):
    """单条关键词命中(段落级)。"""

    paragraph_text: str
    doc_id: int
    doc_role: str | None
    position: str  # "body" | "header" | "footer"
    matched_keywords: list[str]
    source_bidder_id: int  # 关键词来源 bidder(对面 bidder = 被检索方)


class SuspiciousSegment(TypedDict):
    """单条可疑段落(双向命中合并去重后)。

    与 KeywordHit 同结构(source_bidder_id 表示关键词来自哪一方)。
    """

    paragraph_text: str
    doc_id: int
    doc_role: str | None
    position: str
    matched_keywords: list[str]
    source_bidder_id: int


class LLMJudgment(TypedDict, total=False):
    """L-5 LLM 返回结构。"""

    is_cross_contamination: bool
    direct_evidence: bool
    confidence: float
    evidence: list[dict]  # [{type, snippet, position}]


class PairResult(TypedDict, total=False):
    """单 pair (A, B) 的检测结果。"""

    bidder_a_id: int
    bidder_b_id: int
    suspicious_segments: list[SuspiciousSegment]
    truncated: bool
    original_count: int
    llm_judgment: LLMJudgment | None
    llm_failed: bool
    llm_failure_reason: str | None
    is_iron_evidence: bool
    pair_score: float


class DetectionResult(TypedDict, total=False):
    """整个 Agent 检测产出。"""

    pair_results: list[PairResult]
    has_iron_evidence: bool
    downgrade_mode: bool
    participating_subdims: list[str]


__all__ = [
    "KeywordHit",
    "SuspiciousSegment",
    "LLMJudgment",
    "PairResult",
    "DetectionResult",
]
