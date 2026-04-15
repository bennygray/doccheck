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


def test_registry_has_11_agents():
    """C12 扩注册表:10 → 11(新增 global 型 price_anomaly)。"""
    from app.services.detect.registry import EXPECTED_AGENT_COUNT

    assert len(AGENT_REGISTRY) == 11
    assert len(AGENT_REGISTRY) == EXPECTED_AGENT_COUNT


def test_registry_split_7_pair_4_global():
    """C12 后:pair 7 + global 4(新增 price_anomaly)。"""
    pair = [s for s in AGENT_REGISTRY.values() if s.agent_type == "pair"]
    glob = [s for s in AGENT_REGISTRY.values() if s.agent_type == "global"]
    assert len(pair) == 7
    assert len(glob) == 4


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
        "price_anomaly",  # C12 新增
    }
    assert set(AGENT_REGISTRY.keys()) == expected


def test_price_anomaly_is_global():
    spec = get_agent("price_anomaly")
    assert spec is not None
    assert spec.agent_type == "global"


def test_no_dummy_run_after_c13():
    """C13 后 11 Agent 全部 run() 已替换为真实实现,dummy 列表清空。

    验证方式:检查三 global Agent 的 run 函数源模块路径不再含 _dummy。
    """
    import inspect

    for name in ("error_consistency", "image_reuse", "style"):
        spec = get_agent(name)
        assert spec is not None
        src_module = inspect.getmodule(spec.run)
        assert src_module is not None
        # 真实 run 应在对应 Agent 自己的模块,不在 _dummy
        assert "_dummy" not in src_module.__name__, (
            f"{name} run() 仍指向 _dummy 模块"
        )


def test_get_agent_by_name():
    spec = get_agent("text_similarity")
    assert spec is not None
    assert spec.agent_type == "pair"


def test_get_agent_unknown_returns_none():
    assert get_agent("nonexistent_agent_xyz") is None


def test_get_all_agents_returns_list():
    all_agents = get_all_agents()
    assert len(all_agents) == 11


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


# ============================================ C14: contract invariants


def test_c14_agent_count_unchanged():
    """C14 detect-llm-judge 不动注册表;11 Agent 数量保持不变"""
    from app.services.detect.registry import EXPECTED_AGENT_COUNT

    assert EXPECTED_AGENT_COUNT == 11
    assert len(get_all_agents()) == 11


def test_c14_agent_run_result_contract_unchanged():
    """AgentRunResult 仍 3 字段契约,不扩字段"""
    from app.services.detect.context import AgentRunResult

    assert AgentRunResult._fields == ("score", "summary", "evidence_json")


def test_c14_dimension_weights_sum_and_keys():
    """DIMENSION_WEIGHTS 11 键 + 权重和 = 1.00(C12 调整值,C14 不改)"""
    from app.services.detect.judge import DIMENSION_WEIGHTS

    assert len(DIMENSION_WEIGHTS) == 11
    assert round(sum(DIMENSION_WEIGHTS.values()), 4) == 1.0
    expected = {
        "text_similarity",
        "section_similarity",
        "structure_similarity",
        "metadata_author",
        "metadata_time",
        "metadata_machine",
        "price_consistency",
        "price_anomaly",
        "error_consistency",
        "style",
        "image_reuse",
    }
    assert set(DIMENSION_WEIGHTS.keys()) == expected


def test_c14_compute_report_signature_unchanged():
    """compute_report 纯函数签名契约不变(C6~C13 既有调用保持)"""
    import inspect

    from app.services.detect.judge import compute_report

    sig = inspect.signature(compute_report)
    params = list(sig.parameters.keys())
    assert params == ["pair_comparisons", "overall_analyses"]
