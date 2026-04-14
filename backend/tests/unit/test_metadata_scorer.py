"""L1 - metadata_impl/scorer (C10)"""

from __future__ import annotations

from app.services.detect.agents.metadata_impl.scorer import combine_dimension


def test_score_non_none_multiplies_100() -> None:
    dim = {
        "score": 0.67,
        "reason": None,
        "sub_scores": {"author": 1.0, "company": 0.0},
        "hits": [{"field": "author", "value": "X"}],
    }
    agent_score, ev = combine_dimension(dim)
    assert agent_score == 67.0
    assert ev["score"] == 0.67
    assert ev["reason"] is None
    assert sorted(ev["participating_fields"]) == ["author", "company"]


def test_score_none_sentinel() -> None:
    dim = {
        "score": None,
        "reason": "字段缺失",
        "sub_scores": {},
        "hits": [],
    }
    agent_score, ev = combine_dimension(dim)
    assert agent_score == 0.0
    assert ev["score"] is None
    assert ev["reason"] == "字段缺失"
    assert ev["participating_fields"] == []
    assert ev["hits"] == []


def test_machine_uses_hit_field_for_participating() -> None:
    """machine_detector 无 sub_scores,scorer 从 hits 取 field 名。"""
    dim = {
        "score": 0.5,
        "reason": None,
        "hits": [
            {"field": "machine_fingerprint", "value": {"app_name": "x"}},
        ],
    }
    agent_score, ev = combine_dimension(dim)
    assert agent_score == 50.0
    assert ev["participating_fields"] == ["machine_fingerprint"]


def test_rounds_to_two_decimals() -> None:
    dim = {"score": 0.123456, "reason": None, "sub_scores": {"author": 0.2}, "hits": []}
    agent_score, _ = combine_dimension(dim)
    assert agent_score == 12.35
