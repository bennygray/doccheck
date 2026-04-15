"""image_reuse env 配置 (C13)

env 清单(统一 IMAGE_REUSE_ 前缀):
- IMAGE_REUSE_ENABLED (bool, default true)
- IMAGE_REUSE_PHASH_DISTANCE_THRESHOLD (int 0~64, default 5;严格)
- IMAGE_REUSE_MIN_WIDTH (int > 0, default 32;严格)
- IMAGE_REUSE_MIN_HEIGHT (int > 0, default 32;严格)
- IMAGE_REUSE_MAX_PAIRS (int > 0, default 10000;宽松)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImageReuseConfig:
    enabled: bool = True
    phash_distance_threshold: int = 5
    min_width: int = 32
    min_height: int = 32
    max_pairs: int = 10000


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    if raw in ("false", "0", "no", "off"):
        return False
    return True


def _env_positive_int_strict(key: str, default: int) -> int:
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


def _env_positive_int_lenient(key: str, default: int) -> int:
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


def load_config() -> ImageReuseConfig:
    """加载 IMAGE_REUSE_* env。

    关键参数(PHASH_DISTANCE_THRESHOLD 0~64 / MIN_WIDTH/HEIGHT > 0)非法 → ValueError。
    次要参数(MAX_PAIRS)非法 → warn fallback。
    """
    return ImageReuseConfig(
        enabled=_env_bool("IMAGE_REUSE_ENABLED", True),
        phash_distance_threshold=_env_int_in_range_strict(
            "IMAGE_REUSE_PHASH_DISTANCE_THRESHOLD", 5, lo=0, hi=64
        ),
        min_width=_env_positive_int_strict("IMAGE_REUSE_MIN_WIDTH", 32),
        min_height=_env_positive_int_strict("IMAGE_REUSE_MIN_HEIGHT", 32),
        max_pairs=_env_positive_int_lenient("IMAGE_REUSE_MAX_PAIRS", 10000),
    )


__all__ = ["ImageReuseConfig", "load_config"]
