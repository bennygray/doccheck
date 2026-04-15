"""C11 env 配置 (price_impl)

env 清单(统一 PRICE_CONSISTENCY_ 前缀):
- PRICE_CONSISTENCY_TAIL_ENABLED / AMOUNT_PATTERN_ENABLED / ITEM_LIST_ENABLED / SERIES_ENABLED
- PRICE_CONSISTENCY_TAIL_N
- PRICE_CONSISTENCY_AMOUNT_PATTERN_THRESHOLD
- PRICE_CONSISTENCY_ITEM_LIST_THRESHOLD
- PRICE_CONSISTENCY_SERIES_RATIO_VARIANCE_MAX
- PRICE_CONSISTENCY_SERIES_DIFF_CV_MAX
- PRICE_CONSISTENCY_SERIES_MIN_PAIRS
- PRICE_CONSISTENCY_SUBDIM_WEIGHTS("tail,amount_pattern,item_list,series" 顺序)
- PRICE_CONSISTENCY_MAX_ROWS_PER_BIDDER
- PRICE_CONSISTENCY_MAX_HITS_PER_SUBDIM
- PRICE_CONSISTENCY_IRONCLAD_THRESHOLD

解析失败 fallback 默认值 + logger.warning(对齐 C9/C10 风格)。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


_SUBDIMS: tuple[str, ...] = ("tail", "amount_pattern", "item_list", "series")
_DEFAULT_WEIGHTS: dict[str, float] = {
    "tail": 0.25,
    "amount_pattern": 0.25,
    "item_list": 0.3,
    "series": 0.2,
}


@dataclass(frozen=True)
class TailConfig:
    enabled: bool = True
    tail_n: int = 3
    max_hits: int = 20


@dataclass(frozen=True)
class AmountPatternConfig:
    enabled: bool = True
    threshold: float = 0.5
    max_hits: int = 20


@dataclass(frozen=True)
class ItemListConfig:
    enabled: bool = True
    threshold: float = 0.95
    max_hits: int = 20


@dataclass(frozen=True)
class SeriesConfig:
    enabled: bool = True
    ratio_variance_max: float = 0.001
    diff_cv_max: float = 0.01
    min_pairs: int = 3
    max_hits: int = 20


@dataclass(frozen=True)
class ScorerConfig:
    weights: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_WEIGHTS)
    )
    enabled: dict[str, bool] = field(
        default_factory=lambda: {k: True for k in _SUBDIMS}
    )
    order: tuple[str, ...] = _SUBDIMS
    ironclad_threshold: float = 85.0


@dataclass(frozen=True)
class PriceConfig:
    """C11 总配置:嵌套 4 子检测 config + scorer config + 加载层参数。"""

    tail: TailConfig
    amount_pattern: AmountPatternConfig
    item_list: ItemListConfig
    series: SeriesConfig
    scorer: ScorerConfig
    max_rows_per_bidder: int = 5000


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
            logger.warning(
                "%s must be positive, got %s — fallback %s", key, raw, default
            )
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


def load_price_config() -> PriceConfig:
    max_hits = _env_int("PRICE_CONSISTENCY_MAX_HITS_PER_SUBDIM", 20)
    enabled_map = {
        "tail": _env_bool("PRICE_CONSISTENCY_TAIL_ENABLED", True),
        "amount_pattern": _env_bool(
            "PRICE_CONSISTENCY_AMOUNT_PATTERN_ENABLED", True
        ),
        "item_list": _env_bool("PRICE_CONSISTENCY_ITEM_LIST_ENABLED", True),
        "series": _env_bool("PRICE_CONSISTENCY_SERIES_ENABLED", True),
    }
    weights = _env_weights(
        "PRICE_CONSISTENCY_SUBDIM_WEIGHTS", _SUBDIMS, _DEFAULT_WEIGHTS
    )
    return PriceConfig(
        tail=TailConfig(
            enabled=enabled_map["tail"],
            tail_n=_env_int("PRICE_CONSISTENCY_TAIL_N", 3),
            max_hits=max_hits,
        ),
        amount_pattern=AmountPatternConfig(
            enabled=enabled_map["amount_pattern"],
            threshold=_env_float(
                "PRICE_CONSISTENCY_AMOUNT_PATTERN_THRESHOLD", 0.5
            ),
            max_hits=max_hits,
        ),
        item_list=ItemListConfig(
            enabled=enabled_map["item_list"],
            threshold=_env_float(
                "PRICE_CONSISTENCY_ITEM_LIST_THRESHOLD", 0.95
            ),
            max_hits=max_hits,
        ),
        series=SeriesConfig(
            enabled=enabled_map["series"],
            ratio_variance_max=_env_float(
                "PRICE_CONSISTENCY_SERIES_RATIO_VARIANCE_MAX", 0.001
            ),
            diff_cv_max=_env_float(
                "PRICE_CONSISTENCY_SERIES_DIFF_CV_MAX", 0.01
            ),
            min_pairs=_env_int("PRICE_CONSISTENCY_SERIES_MIN_PAIRS", 3),
            max_hits=max_hits,
        ),
        scorer=ScorerConfig(
            weights=weights,
            enabled=enabled_map,
            order=_SUBDIMS,
            ironclad_threshold=_env_float(
                "PRICE_CONSISTENCY_IRONCLAD_THRESHOLD", 85.0
            ),
        ),
        max_rows_per_bidder=_env_int(
            "PRICE_CONSISTENCY_MAX_ROWS_PER_BIDDER", 5000
        ),
    )


__all__ = [
    "PriceConfig",
    "TailConfig",
    "AmountPatternConfig",
    "ItemListConfig",
    "SeriesConfig",
    "ScorerConfig",
    "load_price_config",
]
