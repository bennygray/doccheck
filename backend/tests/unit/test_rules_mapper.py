"""L1 rules_mapper 单元测试 (C17 admin-users)

3 cases: 维度名映射正确/缺失字段 fallback/权重归一化
"""

from __future__ import annotations

from app.services.admin.rules_defaults import DEFAULT_RULES_CONFIG
from app.services.admin.rules_mapper import config_to_engine_params


def test_dimension_mapping_correct():
    """默认配置映射后,所有 13 个引擎维度都有值(fix-bug-triple +2 新维度)。"""
    params = config_to_engine_params(DEFAULT_RULES_CONFIG)
    expected_dims = {
        "metadata_machine",
        "error_consistency",
        "text_similarity",
        "price_consistency",
        "image_reuse",
        "style",
        "metadata_author",
        "section_similarity",
        "structure_similarity",
        "price_anomaly",
        "metadata_time",
        "price_total_match",  # fix-bug-triple-and-direction-high 新增
        "price_overshoot",  # fix-bug-triple-and-direction-high 新增
    }
    assert set(params["weights"].keys()) == expected_dims
    assert set(params["enabled"].keys()) == expected_dims
    # 所有维度默认启用
    assert all(params["enabled"].values())


def test_missing_field_fallback():
    """config 为 None 时返回基于默认值的参数。"""
    params = config_to_engine_params(None)
    assert params["risk_levels"]["high"] == 70
    assert params["risk_levels"]["medium"] == 40
    assert len(params["weights"]) == 13


def test_weights_normalized():
    """权重归一化后总和约等于 1.0。"""
    params = config_to_engine_params(DEFAULT_RULES_CONFIG)
    total = sum(params["weights"].values())
    assert abs(total - 1.0) < 0.01
