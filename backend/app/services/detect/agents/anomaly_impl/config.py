"""C12 env 配置 (anomaly_impl)

env 清单(统一 PRICE_ANOMALY_ 前缀):
- PRICE_ANOMALY_ENABLED (bool, default true)
- PRICE_ANOMALY_MIN_SAMPLE_SIZE (int, default 3;非正数抛 ValueError)
- PRICE_ANOMALY_DEVIATION_THRESHOLD (float, default 0.30;非正数抛 ValueError)
- PRICE_ANOMALY_DIRECTION (str, default 'low';非 low 运行期 fallback + warn)
- PRICE_ANOMALY_BASELINE_ENABLED (bool, default false;true 时 warn 但本期不读)
- PRICE_ANOMALY_MAX_BIDDERS (int, default 50)
- PRICE_ANOMALY_WEIGHT (float, default 1.0)

非法值处理(贴 C11 风格):
- 关键参数(sample_size / deviation_threshold)非法 → 抛 ValueError 在模块加载期暴露
- 次要参数(max_bidders / weight)非法 → logger.warning + fallback 默认
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnomalyConfig:
    enabled: bool = True
    min_sample_size: int = 3
    deviation_threshold: float = 0.30
    direction: str = "low"
    baseline_enabled: bool = False
    max_bidders: int = 50
    weight: float = 1.0


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    if raw in ("false", "0", "no", "off"):
        return False
    return True


def _env_positive_int_strict(key: str, default: int) -> int:
    """关键参数:非法值抛 ValueError(模块加载期暴露)。"""
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError as e:
        raise ValueError(f"{key} must be a positive integer, got {raw!r}") from e
    if v <= 0:
        raise ValueError(f"{key} must be positive, got {v}")
    return v


def _env_positive_float_strict(key: str, default: float) -> float:
    """关键参数:非法值抛 ValueError。"""
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError as e:
        raise ValueError(f"{key} must be a positive float, got {raw!r}") from e
    if v <= 0:
        raise ValueError(f"{key} must be > 0, got {v}")
    return v


def _env_positive_int_lenient(key: str, default: int) -> int:
    """次要参数:非法值 warn + fallback。"""
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        if v <= 0:
            logger.warning(
                "%s must be positive, got %s — fallback %s", key, raw, default
            )
            return default
        return v
    except ValueError:
        logger.warning("%s parse failed %r — fallback %s", key, raw, default)
        return default


def _env_float_lenient(key: str, default: float) -> float:
    """次要参数:非法值 warn + fallback。"""
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
        if v < 0:
            logger.warning(
                "%s must be non-negative, got %s — fallback %s",
                key,
                raw,
                default,
            )
            return default
        return v
    except ValueError:
        logger.warning("%s parse failed %r — fallback %s", key, raw, default)
        return default


def load_anomaly_config() -> AnomalyConfig:
    """加载 PRICE_ANOMALY_* env 配置。

    关键参数非法 → 抛 ValueError;次要参数非法 → warn + fallback。
    baseline_enabled=true 时 warn "本期未实现",仍读取但 run 不会使用。
    """
    baseline_enabled = _env_bool("PRICE_ANOMALY_BASELINE_ENABLED", False)
    if baseline_enabled:
        logger.warning(
            "PRICE_ANOMALY_BASELINE_ENABLED=true but baseline path not "
            "implemented in C12, will fallback to mean-only; follow-up"
        )

    return AnomalyConfig(
        enabled=_env_bool("PRICE_ANOMALY_ENABLED", True),
        min_sample_size=_env_positive_int_strict(
            "PRICE_ANOMALY_MIN_SAMPLE_SIZE", 3
        ),
        deviation_threshold=_env_positive_float_strict(
            "PRICE_ANOMALY_DEVIATION_THRESHOLD", 0.30
        ),
        direction=os.environ.get("PRICE_ANOMALY_DIRECTION", "low").strip()
        or "low",
        baseline_enabled=baseline_enabled,
        max_bidders=_env_positive_int_lenient("PRICE_ANOMALY_MAX_BIDDERS", 50),
        weight=_env_float_lenient("PRICE_ANOMALY_WEIGHT", 1.0),
    )


__all__ = ["AnomalyConfig", "load_anomaly_config"]
