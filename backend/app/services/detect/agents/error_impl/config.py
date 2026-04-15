"""error_consistency env 配置 (C13)

env 清单(统一 ERROR_CONSISTENCY_ 前缀):
- ERROR_CONSISTENCY_ENABLED (bool, default true)
- ERROR_CONSISTENCY_MAX_CANDIDATE_SEGMENTS (int > 0, default 100;严格,RISK-19)
- ERROR_CONSISTENCY_MIN_KEYWORD_LEN (int > 0, default 2;严格,RISK-19)
- ERROR_CONSISTENCY_LLM_TIMEOUT_S (int > 0, default 30;宽松)
- ERROR_CONSISTENCY_LLM_MAX_RETRIES (int >= 0, default 2;宽松)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ErrorConsistencyConfig:
    enabled: bool = True
    max_candidate_segments: int = 100
    min_keyword_len: int = 2
    llm_timeout_s: int = 30
    llm_max_retries: int = 2


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


def load_config() -> ErrorConsistencyConfig:
    """加载 ERROR_CONSISTENCY_* env 配置。

    关键参数(MAX_CANDIDATE_SEGMENTS / MIN_KEYWORD_LEN)非法 → ValueError;
    次要参数(LLM_TIMEOUT_S / LLM_MAX_RETRIES)非法 → warn fallback。
    """
    return ErrorConsistencyConfig(
        enabled=_env_bool("ERROR_CONSISTENCY_ENABLED", True),
        max_candidate_segments=_env_positive_int_strict(
            "ERROR_CONSISTENCY_MAX_CANDIDATE_SEGMENTS", 100
        ),
        min_keyword_len=_env_positive_int_strict(
            "ERROR_CONSISTENCY_MIN_KEYWORD_LEN", 2
        ),
        llm_timeout_s=_env_int_lenient(
            "ERROR_CONSISTENCY_LLM_TIMEOUT_S", 30
        ),
        llm_max_retries=_env_int_lenient(
            "ERROR_CONSISTENCY_LLM_MAX_RETRIES", 2, allow_zero=True
        ),
    )


__all__ = ["ErrorConsistencyConfig", "load_config"]
