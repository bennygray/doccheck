"""L1 - price_impl/scorer (C11)"""

from __future__ import annotations

from app.services.detect.agents.price_impl.config import ScorerConfig
from app.services.detect.agents.price_impl.scorer import combine_subdims


def _default_cfg(**overrides):
    base = ScorerConfig()
    if "weights" in overrides:
        return ScorerConfig(
            weights=overrides["weights"],
            enabled=overrides.get("enabled", base.enabled),
            order=base.order,
            ironclad_threshold=base.ironclad_threshold,
        )
    if "enabled" in overrides:
        return ScorerConfig(
            weights=base.weights,
            enabled=overrides["enabled"],
            order=base.order,
            ironclad_threshold=base.ironclad_threshold,
        )
    return base


def test_partial_skip_partial_hit_normalizes():
    # tail score=0.6 (w=0.25), amount_pattern None (skip), item_list 1.0 (w=0.3),
    # series disabled → total_w=0.55 weighted=0.45 → 0.45/0.55*100 ≈ 81.82
    results = {
        "tail": {"score": 0.6, "reason": None, "hits": []},
        "amount_pattern": {"score": None, "reason": "no data", "hits": []},
        "item_list": {"score": 1.0, "reason": None, "hits": []},
        "series": None,
    }
    cfg = _default_cfg(
        enabled={"tail": True, "amount_pattern": True, "item_list": True, "series": False}
    )
    score, evidence = combine_subdims(results, cfg)
    assert evidence["enabled"] is True
    assert score == 81.82
    assert set(evidence["participating_subdims"]) == {"tail", "item_list"}
    # series 应 enabled=false,amount_pattern enabled=true 但 score=None
    assert evidence["subdims"]["series"]["enabled"] is False
    assert evidence["subdims"]["amount_pattern"]["enabled"] is True
    assert evidence["subdims"]["amount_pattern"]["score"] is None


def test_all_skip_returns_sentinel():
    results = {name: {"score": None, "reason": "no data", "hits": []}
               for name in ScorerConfig().order}
    score, evidence = combine_subdims(results, _default_cfg())
    assert score == 0.0
    assert evidence["enabled"] is False
    assert evidence["participating_subdims"] == []


def test_all_disabled_returns_sentinel():
    results = {name: {"score": 0.5, "reason": None, "hits": []}
               for name in ScorerConfig().order}
    cfg = _default_cfg(enabled={n: False for n in ScorerConfig().order})
    score, evidence = combine_subdims(results, cfg)
    assert score == 0.0
    assert evidence["enabled"] is False
    assert all(
        evidence["subdims"][n]["enabled"] is False
        for n in ScorerConfig().order
    )


def test_subdims_stub_includes_all_four():
    """无论 results 是否完整,subdims 必须含 4 子检测占位。"""
    results = {"tail": {"score": 0.5, "reason": None, "hits": []}}
    score, evidence = combine_subdims(results, _default_cfg())
    assert set(evidence["subdims"].keys()) == {
        "tail", "amount_pattern", "item_list", "series"
    }


def test_score_clamped_to_0_100():
    # 非法权重 0 → 走 sentinel
    cfg = _default_cfg(weights={n: 0.0 for n in ScorerConfig().order})
    results = {n: {"score": 1.0, "reason": None, "hits": []}
               for n in ScorerConfig().order}
    score, evidence = combine_subdims(results, cfg)
    assert score == 0.0
    assert evidence["enabled"] is False
