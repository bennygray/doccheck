"""L1 - style.run() (C13)"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.detect.agents import style
from app.services.detect.agents.style_impl.models import (
    GlobalComparison,
    StyleFeatureBrief,
)


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


def _ctx(n: int = 3, session=None):
    from app.services.detect.context import AgentContext

    bidders = [SimpleNamespace(id=i, name=f"b{i}") for i in range(1, n + 1)]
    return AgentContext(
        project_id=1,
        version=1,
        agent_task=SimpleNamespace(),  # type: ignore[arg-type]
        bidder_a=None,
        bidder_b=None,
        all_bidders=bidders,
        session=session,
    )


@pytest.mark.asyncio
async def test_disabled_early_return(monkeypatch) -> None:
    monkeypatch.setenv("STYLE_ENABLED", "false")
    result = await style.run(_ctx(3, session=_FakeSession()))
    assert result.score == 0.0
    assert result.evidence_json["enabled"] is False


@pytest.mark.asyncio
async def test_normal_full_flow(monkeypatch) -> None:
    monkeypatch.delenv("STYLE_ENABLED", raising=False)

    async def fake_sample(_session, bid, _cfg):
        return ([f"段落{bid}"], False)

    async def fake_s1(_provider, bid, _paras, _cfg):
        return StyleFeatureBrief(
            bidder_id=bid,
            **{
                "用词偏好": "x",
                "句式特点": "y",
                "标点习惯": "z",
                "段落组织": "w",
            },
        )

    async def fake_s2(_provider, _briefs, _cfg):
        return GlobalComparison(
            consistent_groups=[  # type: ignore[typeddict-item]
                {
                    "bidder_ids": [1, 2],
                    "consistency_score": 0.8,
                    "typical_features": "common",
                }
            ]
        )

    monkeypatch.setattr("app.services.detect.agents.style.sample", fake_sample)
    monkeypatch.setattr("app.services.detect.agents.style.call_l8_stage1", fake_s1)
    monkeypatch.setattr("app.services.detect.agents.style.call_l8_stage2", fake_s2)

    result = await style.run(_ctx(3, session=_FakeSession()))
    assert result.score > 0
    assert result.evidence_json["grouping_strategy"] == "single"
    assert len(result.evidence_json["global_comparison"]["consistent_groups"]) == 1


@pytest.mark.asyncio
async def test_stage1_failure_skip(monkeypatch) -> None:
    async def fake_sample(_session, bid, _cfg):
        return (["段落"], False)

    async def fake_s1_fail(*args, **kwargs):
        return None  # Stage1 failed

    monkeypatch.setattr("app.services.detect.agents.style.sample", fake_sample)
    monkeypatch.setattr("app.services.detect.agents.style.call_l8_stage1", fake_s1_fail)

    result = await style.run(_ctx(3, session=_FakeSession()))
    assert result.score == 0.0
    assert "Stage1" in result.evidence_json["skip_reason"]


@pytest.mark.asyncio
async def test_stage2_failure_skip(monkeypatch) -> None:
    async def fake_sample(_session, bid, _cfg):
        return (["段落"], False)

    async def fake_s1(*args, **kwargs):
        return StyleFeatureBrief(
            bidder_id=1,
            **{
                "用词偏好": "x",
                "句式特点": "y",
                "标点习惯": "z",
                "段落组织": "w",
            },
        )

    async def fake_s2(*args, **kwargs):
        return None  # Stage2 failed

    monkeypatch.setattr("app.services.detect.agents.style.sample", fake_sample)
    monkeypatch.setattr("app.services.detect.agents.style.call_l8_stage1", fake_s1)
    monkeypatch.setattr("app.services.detect.agents.style.call_l8_stage2", fake_s2)

    result = await style.run(_ctx(3, session=_FakeSession()))
    assert result.score == 0.0
    assert "Stage2" in result.evidence_json["skip_reason"]


@pytest.mark.asyncio
async def test_grouping_strategy_grouped(monkeypatch) -> None:
    """>20 bidder → grouping_strategy='grouped'。"""
    async def fake_sample(_session, bid, _cfg):
        return ([f"p{bid}"], False)

    async def fake_s1(_provider, bid, _paras, _cfg):
        return StyleFeatureBrief(bidder_id=bid, **{"用词偏好": "x", "句式特点": "y", "标点习惯": "z", "段落组织": "w"})

    async def fake_s2(*args, **kwargs):
        return GlobalComparison(consistent_groups=[])  # type: ignore[typeddict-item]

    monkeypatch.setattr("app.services.detect.agents.style.sample", fake_sample)
    monkeypatch.setattr("app.services.detect.agents.style.call_l8_stage1", fake_s1)
    monkeypatch.setattr("app.services.detect.agents.style.call_l8_stage2", fake_s2)

    # 25 bidder > 20 threshold
    result = await style.run(_ctx(25, session=_FakeSession()))
    assert result.evidence_json["grouping_strategy"] == "grouped"
    assert result.evidence_json["group_count"] == 2


@pytest.mark.asyncio
async def test_grouping_single_for_5_bidders(monkeypatch) -> None:
    async def fake_sample(_session, bid, _cfg):
        return ([f"p{bid}"], False)

    async def fake_s1(_provider, bid, _paras, _cfg):
        return StyleFeatureBrief(bidder_id=bid, **{"用词偏好": "x", "句式特点": "y", "标点习惯": "z", "段落组织": "w"})

    async def fake_s2(*args, **kwargs):
        return GlobalComparison(consistent_groups=[])  # type: ignore[typeddict-item]

    monkeypatch.setattr("app.services.detect.agents.style.sample", fake_sample)
    monkeypatch.setattr("app.services.detect.agents.style.call_l8_stage1", fake_s1)
    monkeypatch.setattr("app.services.detect.agents.style.call_l8_stage2", fake_s2)

    result = await style.run(_ctx(5, session=_FakeSession()))
    assert result.evidence_json["grouping_strategy"] == "single"
    assert result.evidence_json["group_count"] == 1


@pytest.mark.asyncio
async def test_limitation_note_always_filled(monkeypatch) -> None:
    """evidence.limitation_note 必填(spec §F-DA-06 强制)。"""
    monkeypatch.setenv("STYLE_ENABLED", "false")
    result = await style.run(_ctx(3, session=_FakeSession()))
    assert "代写" in result.evidence_json["limitation_note"]


@pytest.mark.asyncio
async def test_insufficient_sample_marked(monkeypatch) -> None:
    async def fake_sample(_session, bid, _cfg):
        # 标记 insufficient
        return ([f"p{bid}"], True)

    async def fake_s1(_provider, bid, _paras, _cfg):
        return StyleFeatureBrief(bidder_id=bid, **{"用词偏好": "x", "句式特点": "y", "标点习惯": "z", "段落组织": "w"})

    async def fake_s2(*args, **kwargs):
        return GlobalComparison(consistent_groups=[])  # type: ignore[typeddict-item]

    monkeypatch.setattr("app.services.detect.agents.style.sample", fake_sample)
    monkeypatch.setattr("app.services.detect.agents.style.call_l8_stage1", fake_s1)
    monkeypatch.setattr("app.services.detect.agents.style.call_l8_stage2", fake_s2)

    result = await style.run(_ctx(3, session=_FakeSession()))
    assert len(result.evidence_json["insufficient_sample_bidders"]) == 3


@pytest.mark.asyncio
async def test_iron_evidence_always_false(monkeypatch) -> None:
    """style 非铁证维度,has_iron_evidence 不应标 true。"""
    monkeypatch.setenv("STYLE_ENABLED", "false")
    result = await style.run(_ctx(3, session=_FakeSession()))
    assert result.evidence_json.get("has_iron_evidence") is not True
