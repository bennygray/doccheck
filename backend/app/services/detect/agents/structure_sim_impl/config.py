"""structure_similarity Agent 运行期配置 (C9)

- STRUCTURE_SIM_MIN_CHAPTERS          默认 3      章节数 < 此值 → 目录维度 None
- STRUCTURE_SIM_MIN_SHEET_ROWS        默认 2      非空行 < 此值 → sheet 不参与
- STRUCTURE_SIM_WEIGHTS               默认 "0.4,0.3,0.3"  三维度权重
- STRUCTURE_SIM_FIELD_JACCARD_SUB_WEIGHTS  默认 "0.4,0.3,0.3"  字段子权重
- STRUCTURE_SIM_MAX_ROWS_PER_SHEET    默认 5000   xlsx 每 sheet 行数上限

复用 C8 env(通过 C8 chapter_parser 内部读取):
- SECTION_SIM_MIN_CHAPTER_CHARS              章节内字符合并阈值(chapter_parser 用)
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS: tuple[float, float, float] = (0.4, 0.3, 0.3)
DEFAULT_FIELD_SUB_WEIGHTS: tuple[float, float, float] = (0.4, 0.3, 0.3)


def min_chapters() -> int:
    try:
        v = int(os.environ.get("STRUCTURE_SIM_MIN_CHAPTERS", "3"))
        return v if v > 0 else 3
    except ValueError:
        return 3


def min_sheet_rows() -> int:
    try:
        v = int(os.environ.get("STRUCTURE_SIM_MIN_SHEET_ROWS", "2"))
        return v if v > 0 else 2
    except ValueError:
        return 2


def _parse_triple_weights(
    raw: str, default: tuple[float, float, float]
) -> tuple[float, float, float]:
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 3:
        logger.warning(
            "STRUCTURE_SIM weights must have 3 floats, got %r, fallback %s",
            raw,
            default,
        )
        return default
    try:
        vals = tuple(float(p) for p in parts)
    except ValueError:
        logger.warning(
            "STRUCTURE_SIM weights parse failed %r, fallback %s", raw, default
        )
        return default
    if any(v < 0 for v in vals) or sum(vals) <= 0:
        logger.warning(
            "STRUCTURE_SIM weights invalid %s, fallback %s", vals, default
        )
        return default
    return vals  # type: ignore[return-value]


def weights() -> tuple[float, float, float]:
    raw = os.environ.get("STRUCTURE_SIM_WEIGHTS", "").strip()
    if not raw:
        return DEFAULT_WEIGHTS
    return _parse_triple_weights(raw, DEFAULT_WEIGHTS)


def field_sub_weights() -> tuple[float, float, float]:
    raw = os.environ.get(
        "STRUCTURE_SIM_FIELD_JACCARD_SUB_WEIGHTS", ""
    ).strip()
    if not raw:
        return DEFAULT_FIELD_SUB_WEIGHTS
    return _parse_triple_weights(raw, DEFAULT_FIELD_SUB_WEIGHTS)


def max_rows_per_sheet() -> int:
    try:
        v = int(os.environ.get("STRUCTURE_SIM_MAX_ROWS_PER_SHEET", "5000"))
        return v if v > 0 else 5000
    except ValueError:
        return 5000
