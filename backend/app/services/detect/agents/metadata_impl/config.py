"""C10 env 配置 (metadata_impl)

env 清单(统一 METADATA_ 前缀):
- METADATA_AUTHOR_ENABLED / METADATA_TIME_ENABLED / METADATA_MACHINE_ENABLED
- METADATA_TIME_CLUSTER_WINDOW_MIN
- METADATA_AUTHOR_SUBDIM_WEIGHTS("author,last_saved_by,company" 顺序)
- METADATA_TIME_SUBDIM_WEIGHTS("modified,created" 顺序)
- METADATA_IRONCLAD_THRESHOLD
- METADATA_MAX_HITS_PER_AGENT

解析失败 fallback 默认值 + logger.warning(与 C9 STRUCTURE_SIM_WEIGHTS 风格一致)。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


_DEFAULT_AUTHOR_WEIGHTS = {
    "author": 0.5,
    "last_saved_by": 0.3,
    "company": 0.2,
}
_DEFAULT_TIME_WEIGHTS = {
    "modified_at_cluster": 0.7,
    "created_at_match": 0.3,
}
_AUTHOR_FIELDS = ("author", "last_saved_by", "company")
_TIME_FIELDS = ("modified_at_cluster", "created_at_match")


@dataclass(frozen=True)
class AuthorConfig:
    enabled: bool = True
    subdim_weights: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_AUTHOR_WEIGHTS)
    )
    ironclad_threshold: float = 85.0
    max_hits_per_agent: int = 50


@dataclass(frozen=True)
class TimeConfig:
    enabled: bool = True
    window_min: int = 5
    subdim_weights: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_TIME_WEIGHTS)
    )
    ironclad_threshold: float = 85.0
    max_hits_per_agent: int = 50


@dataclass(frozen=True)
class MachineConfig:
    enabled: bool = True
    ironclad_threshold: float = 85.0
    max_hits_per_agent: int = 50


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    if raw in ("false", "0", "no", "off"):
        return False
    return True


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        if v <= 0:
            logger.warning("%s must be positive, got %s — fallback %s", key, raw, default)
            return default
        return v
    except ValueError:
        logger.warning("%s parse failed %r — fallback %s", key, raw, default)
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s parse failed %r — fallback %s", key, raw, default)
        return default


def _env_weights(
    key: str, fields: tuple[str, ...], defaults: dict[str, float]
) -> dict[str, float]:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return dict(defaults)
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != len(fields):
        logger.warning(
            "%s expects %d comma-separated floats, got %r — fallback default",
            key,
            len(fields),
            raw,
        )
        return dict(defaults)
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        logger.warning("%s parse failed %r — fallback default", key, raw)
        return dict(defaults)
    if any(v < 0 for v in vals) or sum(vals) <= 0:
        logger.warning(
            "%s non-positive weights %r — fallback default", key, raw
        )
        return dict(defaults)
    return dict(zip(fields, vals, strict=True))


def load_author_config() -> AuthorConfig:
    return AuthorConfig(
        enabled=_env_bool("METADATA_AUTHOR_ENABLED", True),
        subdim_weights=_env_weights(
            "METADATA_AUTHOR_SUBDIM_WEIGHTS",
            _AUTHOR_FIELDS,
            _DEFAULT_AUTHOR_WEIGHTS,
        ),
        ironclad_threshold=_env_float("METADATA_IRONCLAD_THRESHOLD", 85.0),
        max_hits_per_agent=_env_int("METADATA_MAX_HITS_PER_AGENT", 50),
    )


def load_time_config() -> TimeConfig:
    return TimeConfig(
        enabled=_env_bool("METADATA_TIME_ENABLED", True),
        window_min=_env_int("METADATA_TIME_CLUSTER_WINDOW_MIN", 5),
        subdim_weights=_env_weights(
            "METADATA_TIME_SUBDIM_WEIGHTS",
            _TIME_FIELDS,
            _DEFAULT_TIME_WEIGHTS,
        ),
        ironclad_threshold=_env_float("METADATA_IRONCLAD_THRESHOLD", 85.0),
        max_hits_per_agent=_env_int("METADATA_MAX_HITS_PER_AGENT", 50),
    )


def load_machine_config() -> MachineConfig:
    return MachineConfig(
        enabled=_env_bool("METADATA_MACHINE_ENABLED", True),
        ironclad_threshold=_env_float("METADATA_IRONCLAD_THRESHOLD", 85.0),
        max_hits_per_agent=_env_int("METADATA_MAX_HITS_PER_AGENT", 50),
    )


__all__ = [
    "AuthorConfig",
    "TimeConfig",
    "MachineConfig",
    "load_author_config",
    "load_time_config",
    "load_machine_config",
]
