"""style env 配置 (C13)

env 清单(统一 STYLE_ 前缀):
- STYLE_ENABLED (bool, default true)
- STYLE_GROUP_THRESHOLD (int >= 2, default 20;严格)
- STYLE_SAMPLE_PER_BIDDER (int 5~10, default 8;严格,贴 spec L-8 5-10 段)
- STYLE_TFIDF_FILTER_RATIO (float 0~1, default 0.3;宽松)
- STYLE_LLM_TIMEOUT_S (int > 0, default 60;宽松)
- STYLE_LLM_MAX_RETRIES (int >= 0, default 2;宽松)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StyleConfig:
    enabled: bool = True
    group_threshold: int = 20
    sample_per_bidder: int = 8
    tfidf_filter_ratio: float = 0.3
    llm_timeout_s: int = 60
    llm_max_retries: int = 2


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    if raw in ("false", "0", "no", "off"):
        return False
    return True


def _env_int_min_strict(key: str, default: int, *, min_val: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError as e:
        raise ValueError(f"{key} must be an integer, got {raw!r}") from e
    if v < min_val:
        raise ValueError(f"{key} must be >= {min_val}, got {v}")
    return v


def _env_int_in_range_strict(
    key: str, default: int, *, lo: int, hi: int
) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError as e:
        raise ValueError(f"{key} must be an integer, got {raw!r}") from e
    if v < lo or v > hi:
        raise ValueError(f"{key} must be in [{lo}, {hi}], got {v}")
    return v


def _env_float_in_range_lenient(
    key: str, default: float, *, lo: float, hi: float
) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        logger.warning("%s parse failed %r — fallback %s", key, raw, default)
        return default
    if v < lo or v > hi:
        logger.warning(
            "%s must be in [%s, %s], got %s — fallback %s",
            key,
            lo,
            hi,
            raw,
            default,
        )
        return default
    return v


def _env_int_lenient(key: str, default: int, *, allow_zero: bool = False) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        if (v < 0) or (not allow_zero and v == 0):
            logger.warning(
                "%s must be %s, got %s — fallback %s",
                key,
                "positive" if not allow_zero else "non-negative",
                raw,
                default,
            )
            return default
        return v
    except ValueError:
        logger.warning("%s parse failed %r — fallback %s", key, raw, default)
        return default


def load_config() -> StyleConfig:
    return StyleConfig(
        enabled=_env_bool("STYLE_ENABLED", True),
        group_threshold=_env_int_min_strict(
            "STYLE_GROUP_THRESHOLD", 20, min_val=2
        ),
        sample_per_bidder=_env_int_in_range_strict(
            "STYLE_SAMPLE_PER_BIDDER", 8, lo=5, hi=10
        ),
        tfidf_filter_ratio=_env_float_in_range_lenient(
            "STYLE_TFIDF_FILTER_RATIO", 0.3, lo=0.0, hi=1.0
        ),
        llm_timeout_s=_env_int_lenient("STYLE_LLM_TIMEOUT_S", 60),
        llm_max_retries=_env_int_lenient(
            "STYLE_LLM_MAX_RETRIES", 2, allow_zero=True
        ),
    )


__all__ = ["StyleConfig", "load_config"]
