"""L1 - detect/registry 单元测试 (C6 §9.1)"""

from __future__ import annotations

import pytest

from app.services.detect import agents  # noqa: F401 - trigger registration
from app.services.detect.context import PreflightResult
from app.services.detect.registry import (
    AGENT_REGISTRY,
    get_agent,
    get_all_agents,
    register_agent,
)


def test_registry_has_10_agents():
    assert len(AGENT_REGISTRY) == 10


def test_registry_split_7_pair_3_global():
    pair = [s for s in AGENT_REGISTRY.values() if s.agent_type == "pair"]
    glob = [s for s in AGENT_REGISTRY.values() if s.agent_type == "global"]
    assert len(pair) == 7
    assert len(glob) == 3


def test_registry_expected_names():
    expected = {
        "text_similarity",
        "section_similarity",
        "structure_similarity",
        "metadata_author",
        "metadata_time",
        "metadata_machine",
        "price_consistency",
        "error_consistency",
        "style",
        "image_reuse",
    }
    assert set(AGENT_REGISTRY.keys()) == expected


def test_get_agent_by_name():
    spec = get_agent("text_similarity")
    assert spec is not None
    assert spec.agent_type == "pair"


def test_get_agent_unknown_returns_none():
    assert get_agent("nonexistent_agent_xyz") is None


def test_get_all_agents_returns_list():
    all_agents = get_all_agents()
    assert len(all_agents) == 10


def test_duplicate_register_raises():
    async def _pf(ctx):
        return PreflightResult("ok")

    # 首次注册 OK
    @register_agent("test_duplicate_x", "pair", _pf)
    async def _r1(ctx):
        pass

    # 再次注册 raise
    with pytest.raises(ValueError, match="already registered"):

        @register_agent("test_duplicate_x", "pair", _pf)
        async def _r2(ctx):
            pass

    # 清理注册表(避免影响其他 test)
    AGENT_REGISTRY.pop("test_duplicate_x", None)
