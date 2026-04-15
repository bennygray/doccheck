"""L1 - style_impl/scorer (C13)"""

from __future__ import annotations

from app.services.detect.agents.style_impl.scorer import (
    LIMITATION_NOTE,
    compute_score,
)


def test_none_comparison() -> None:
    assert compute_score(None) == 0.0


def test_no_groups() -> None:
    assert compute_score({"consistent_groups": []}) == 0.0  # type: ignore[arg-type]


def test_single_group_high_score() -> None:
    # 1 group * 30 + 0.9 * 50 = 75
    score = compute_score(
        {"consistent_groups": [{"consistency_score": 0.9, "bidder_ids": [1, 2], "typical_features": ""}]}  # type: ignore[arg-type]
    )
    assert score == 75.0


def test_multiple_groups() -> None:
    # 2 groups * 30 + 0.8 * 50 = 100 cap
    score = compute_score(
        {
            "consistent_groups": [  # type: ignore[arg-type]
                {"consistency_score": 0.8, "bidder_ids": [1, 2], "typical_features": ""},
                {"consistency_score": 0.5, "bidder_ids": [3, 4], "typical_features": ""},
            ]
        }
    )
    assert score == 100.0


def test_capped_at_100() -> None:
    score = compute_score(
        {  # type: ignore[arg-type]
            "consistent_groups": [
                {"consistency_score": 1.0, "bidder_ids": [1, 2], "typical_features": ""}
            ] * 10
        }
    )
    assert score == 100.0


def test_limitation_note_constant() -> None:
    """验证 spec §F-DA-06 要求的局限性说明存在。"""
    assert "代写" in LIMITATION_NOTE
    assert "综合判断" in LIMITATION_NOTE
