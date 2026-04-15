"""L1 - image_reuse.run() (C13)"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.detect.agents import image_reuse


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


def _ctx(session=None) -> object:
    from app.services.detect.context import AgentContext

    return AgentContext(
        project_id=1,
        version=1,
        agent_task=SimpleNamespace(),  # type: ignore[arg-type]
        bidder_a=None,
        bidder_b=None,
        all_bidders=[SimpleNamespace(id=1), SimpleNamespace(id=2)],
        session=session,
    )


@pytest.mark.asyncio
async def test_disabled_early_return(monkeypatch) -> None:
    monkeypatch.setenv("IMAGE_REUSE_ENABLED", "false")
    result = await image_reuse.run(_ctx(session=_FakeSession()))
    assert result.score == 0.0
    assert result.evidence_json["enabled"] is False


@pytest.mark.asyncio
async def test_md5_hit_normal(monkeypatch) -> None:
    monkeypatch.delenv("IMAGE_REUSE_ENABLED", raising=False)

    async def fake_compare(_session, _pid, _cfg):
        return {
            "md5_matches": [
                {
                    "md5": "x",
                    "doc_id_a": 1,
                    "doc_id_b": 2,
                    "bidder_a_id": 1,
                    "bidder_b_id": 2,
                    "position_a": None,
                    "position_b": None,
                    "hit_strength": 1.0,
                    "match_type": "byte_match",
                }
            ],
            "phash_matches": [],
            "truncated": False,
            "original_count": 1,
        }

    monkeypatch.setattr(
        "app.services.detect.agents.image_reuse.compare", fake_compare
    )
    result = await image_reuse.run(_ctx(session=_FakeSession()))
    assert result.score > 0
    assert len(result.evidence_json["md5_matches"]) == 1


@pytest.mark.asyncio
async def test_phash_hit_normal(monkeypatch) -> None:
    async def fake_compare(*args, **kwargs):
        return {
            "md5_matches": [],
            "phash_matches": [
                {"hit_strength": 0.9, "distance": 3, "match_type": "visual_similar"}
            ],
            "truncated": False,
            "original_count": 1,
        }

    monkeypatch.setattr(
        "app.services.detect.agents.image_reuse.compare", fake_compare
    )
    result = await image_reuse.run(_ctx(session=_FakeSession()))
    assert result.score > 0


@pytest.mark.asyncio
async def test_no_comparable_images_skip(monkeypatch) -> None:
    """小图过滤后 0 张 → skip 哨兵。"""
    async def fake_compare(*args, **kwargs):
        return {
            "md5_matches": [],
            "phash_matches": [],
            "truncated": False,
            "original_count": 0,
        }

    monkeypatch.setattr(
        "app.services.detect.agents.image_reuse.compare", fake_compare
    )
    result = await image_reuse.run(_ctx(session=_FakeSession()))
    assert result.score == 0.0
    assert (
        result.evidence_json["skip_reason"]
        == "no_comparable_images_after_size_filter"
    )


@pytest.mark.asyncio
async def test_is_iron_evidence_always_false(monkeypatch) -> None:
    """image_reuse 本期不升铁证 — has_iron_evidence 字段应缺失或 null。"""
    async def fake_compare(*args, **kwargs):
        return {
            "md5_matches": [{"hit_strength": 1.0}],
            "phash_matches": [],
            "truncated": False,
            "original_count": 1,
        }

    monkeypatch.setattr(
        "app.services.detect.agents.image_reuse.compare", fake_compare
    )
    result = await image_reuse.run(_ctx(session=_FakeSession()))
    # evidence 占位字段
    assert result.evidence_json["llm_non_generic_judgment"] is None
    # judge.py 不会 读到 has_iron_evidence=true
    assert result.evidence_json.get("has_iron_evidence") is not True


@pytest.mark.asyncio
async def test_compare_exception_caught(monkeypatch) -> None:
    async def fake_compare(*args, **kwargs):
        raise RuntimeError("DB boom")

    monkeypatch.setattr(
        "app.services.detect.agents.image_reuse.compare", fake_compare
    )
    result = await image_reuse.run(_ctx(session=_FakeSession()))
    assert result.score == 0.0
    assert "RuntimeError" in result.evidence_json["error"]
