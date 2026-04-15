"""image_reuse 数据契约 (C13)"""

from __future__ import annotations

from typing import TypedDict


class MD5Match(TypedDict):
    md5: str
    doc_id_a: int
    doc_id_b: int
    bidder_a_id: int
    bidder_b_id: int
    position_a: str | None
    position_b: str | None
    hit_strength: float  # 始终 1.0
    match_type: str  # "byte_match"


class PHashMatch(TypedDict):
    phash_a: str
    phash_b: str
    distance: int
    hit_strength: float  # 1 - d/64
    doc_id_a: int
    doc_id_b: int
    bidder_a_id: int
    bidder_b_id: int
    position_a: str | None
    position_b: str | None
    match_type: str  # "visual_similar"


class DetectionResult(TypedDict, total=False):
    md5_matches: list[MD5Match]
    phash_matches: list[PHashMatch]
    truncated: bool
    original_count: int


__all__ = ["MD5Match", "PHashMatch", "DetectionResult"]
