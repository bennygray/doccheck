"""L1 - error_impl/scorer (C13)"""

from __future__ import annotations

from app.services.detect.agents.error_impl.models import (
    LLMJudgment,
    PairResult,
    SuspiciousSegment,
)
from app.services.detect.agents.error_impl.scorer import (
    compute_agent_score,
    compute_pair_score,
)


def _seg(i: int = 0) -> SuspiciousSegment:
    return SuspiciousSegment(
        paragraph_text=f"{i}",
        doc_id=i,
        doc_role="t",
        position="body",
        matched_keywords=["k"],
        source_bidder_id=1,
    )


def test_zero_hits_zero_score() -> None:
    assert compute_pair_score([], None) == 0.0


def test_hits_only_no_judgment() -> None:
    score = compute_pair_score([_seg(0), _seg(1)], None)
    assert score == 40.0


def test_iron_evidence_bonus() -> None:
    j: LLMJudgment = {
        "is_cross_contamination": True,
        "direct_evidence": True,
        "confidence": 0.5,
    }
    score = compute_pair_score([_seg(0)], j)
    # base 20 + iron 40 + confidence 0.5*20=10 = 70
    assert score == 70.0


def test_contamination_only_no_iron() -> None:
    j: LLMJudgment = {
        "is_cross_contamination": True,
        "direct_evidence": False,
        "confidence": 0.8,
    }
    score = compute_pair_score([_seg(0)], j)
    # base 20 + 0.8*20=16 = 36
    assert score == 36.0


def test_score_capped_at_100() -> None:
    j: LLMJudgment = {
        "is_cross_contamination": True,
        "direct_evidence": True,
        "confidence": 1.0,
    }
    # base 200 (10 segs * 20) + 40 + 20 = 260 → cap 100
    score = compute_pair_score([_seg(i) for i in range(10)], j)
    assert score == 100.0


def test_compute_agent_score_max() -> None:
    pairs: list[PairResult] = [
        PairResult(
            bidder_a_id=1, bidder_b_id=2, suspicious_segments=[],
            truncated=False, original_count=0, llm_judgment=None,
            llm_failed=False, llm_failure_reason=None,
            is_iron_evidence=False, pair_score=30.0,
        ),
        PairResult(
            bidder_a_id=1, bidder_b_id=3, suspicious_segments=[],
            truncated=False, original_count=0, llm_judgment=None,
            llm_failed=False, llm_failure_reason=None,
            is_iron_evidence=False, pair_score=70.0,
        ),
    ]
    assert compute_agent_score(pairs) == 70.0


def test_compute_agent_score_empty() -> None:
    assert compute_agent_score([]) == 0.0
