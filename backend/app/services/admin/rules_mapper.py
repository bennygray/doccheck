"""SystemConfig JSON ↔ 引擎参数映射 (C17 admin-users)

requirements.md §8 的面向用户维度名（10 个）与代码内部维度名（11 个）不一致。
本模块提供双向映射，使 SystemConfig JSON 面向用户，引擎读取时做转换。
"""

from __future__ import annotations

from app.services.admin.rules_defaults import DEFAULT_RULES_CONFIG

# requirements.md §8 维度名 → 代码 DIMENSION_WEIGHTS key
# 注意一对多：software_metadata → metadata_author; operation_time → metadata_time
# pricing_pattern → section_similarity + structure_similarity (共享 enabled)
_DIM_TO_ENGINE: dict[str, list[str]] = {
    "hardware_fingerprint": ["metadata_machine"],
    "error_consistency": ["error_consistency"],
    "text_similarity": ["text_similarity"],
    "price_similarity": ["price_consistency"],
    "image_reuse": ["image_reuse"],
    "language_style": ["style"],
    "software_metadata": ["metadata_author"],
    "pricing_pattern": ["section_similarity", "structure_similarity"],
    "price_ceiling": ["price_anomaly"],
    "operation_time": ["metadata_time"],
}


def config_to_engine_params(config: dict | None) -> dict:
    """将 SystemConfig JSON 转换为引擎可用的参数字典。

    返回:
        {
            "weights": {engine_dim: float, ...},  # 归一化后的权重
            "enabled": {engine_dim: bool, ...},
            "llm_enabled": {engine_dim: bool, ...},
            "risk_levels": {"high": int, "medium": int},
            "dim_thresholds": {engine_dim: {param: value}, ...},
            "global": {key: value, ...},  # 非维度级参数
        }
    """
    if config is None:
        config = DEFAULT_RULES_CONFIG

    dims = config.get("dimensions", {})

    weights: dict[str, float] = {}
    enabled: dict[str, bool] = {}
    llm_enabled: dict[str, bool] = {}
    dim_thresholds: dict[str, dict] = {}

    for ui_name, engine_names in _DIM_TO_ENGINE.items():
        dim_cfg = dims.get(ui_name, {})
        dim_enabled = dim_cfg.get("enabled", True)
        dim_llm = dim_cfg.get("llm_enabled", True)
        dim_weight = dim_cfg.get("weight", 0)

        # 提取维度特有阈值（排除 enabled/weight/llm_enabled）
        thresholds = {
            k: v
            for k, v in dim_cfg.items()
            if k not in ("enabled", "weight", "llm_enabled")
        }

        for engine_name in engine_names:
            enabled[engine_name] = dim_enabled
            llm_enabled[engine_name] = dim_llm
            dim_thresholds[engine_name] = thresholds

            if dim_weight > 0:
                # 一对多时平分权重
                weights[engine_name] = dim_weight / len(engine_names)
            else:
                weights[engine_name] = 0

    # 权重归一化为小数（config 中是 0~100 的整数）
    total = sum(weights.values())
    if total > 0:
        weights = {k: round(v / total, 4) for k, v in weights.items()}

    # 全局参数
    global_params = {
        "risk_levels": config.get("risk_levels", {"high": 70, "medium": 40}),
        "doc_role_keywords": config.get("doc_role_keywords", {}),
        "hardware_keywords": config.get("hardware_keywords", []),
        "metadata_whitelist": config.get("metadata_whitelist", []),
        "min_paragraph_length": config.get("min_paragraph_length", 50),
        "file_retention_days": config.get("file_retention_days", 90),
    }

    return {
        "weights": weights,
        "enabled": enabled,
        "llm_enabled": llm_enabled,
        "risk_levels": config.get("risk_levels", {"high": 70, "medium": 40}),
        "dim_thresholds": dim_thresholds,
        "global": global_params,
    }
