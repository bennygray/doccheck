"""L1 - image_impl/scorer (C13)"""

from __future__ import annotations

from app.services.detect.agents.image_impl.models import DetectionResult
from app.services.detect.agents.image_impl.scorer import compute_score


def test_no_hits_zero_score() -> None:
    assert compute_score(DetectionResult(md5_matches=[], phash_matches=[])) == 0.0


def test_single_md5_hit() -> None:
    r = DetectionResult(
        md5_matches=[{"hit_strength": 1.0, "match_type": "byte_match"}],  # type: ignore[list-item]
        phash_matches=[],
    )
    assert compute_score(r) == 30.0


def test_multiple_phash_sum() -> None:
    r = DetectionResult(
        md5_matches=[],
        phash_matches=[
            {"hit_strength": 0.9},  # type: ignore[list-item]
            {"hit_strength": 0.8},  # type: ignore[list-item]
        ],
    )
    # 0 * 30 + (0.9 + 0.8) * 10 = 17
    assert compute_score(r) == 17.0


def test_mixed_md5_and_phash() -> None:
    r = DetectionResult(
        md5_matches=[{"hit_strength": 1.0}],  # type: ignore[list-item]
        phash_matches=[{"hit_strength": 0.9}],  # type: ignore[list-item]
    )
    # 30 + 9 = 39
    assert compute_score(r) == 39.0


def test_capped_at_100() -> None:
    r = DetectionResult(
        md5_matches=[{"hit_strength": 1.0}] * 5,  # type: ignore[list-item]
        phash_matches=[{"hit_strength": 1.0}] * 5,  # type: ignore[list-item]
    )
    # 5*30 + 5*10 = 200 → cap 100
    assert compute_score(r) == 100.0
