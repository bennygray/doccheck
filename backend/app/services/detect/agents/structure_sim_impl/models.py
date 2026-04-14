"""C9 structure_sim_impl dataclass 模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DirResult:
    """目录结构维度结果。"""

    score: float  # 0~1
    titles_a_count: int
    titles_b_count: int
    lcs_length: int
    sample_titles_matched: list[str]  # 前 10 条(归一化前原文)
    doc_id_a: int | None = None
    doc_id_b: int | None = None


@dataclass(frozen=True)
class SheetFieldResult:
    """单对 sheet 的字段结构评分。"""

    sheet_name: str
    header_sim: float
    bitmask_sim: float
    merged_cells_sim: float
    sub_score: float  # 加权合并


@dataclass(frozen=True)
class FieldSimResult:
    """字段结构维度整体结果。"""

    score: float  # 0~1,= max(per_sheet.sub_score)
    per_sheet: list[SheetFieldResult]  # 前 5 sheet


@dataclass(frozen=True)
class SheetFillResult:
    """单对 sheet 的填充模式评分。"""

    sheet_name: str
    score: float  # 0~1
    matched_pattern_lines: int  # multiset 交集元素个数
    sample_patterns: list[str]  # 前 10 条高频共享 pattern


@dataclass(frozen=True)
class FillSimResult:
    """表单填充模式维度整体结果。"""

    score: float  # 0~1
    per_sheet: list[SheetFillResult]  # 前 5 sheet


@dataclass(frozen=True)
class AggregateResult:
    """三维度聚合输出。"""

    score: float | None  # 0~100 或 None(全维度 skip)
    participating_dimensions: list[str]
    weights_used: dict[str, float]
    is_ironclad: bool
    evidence: dict = field(default_factory=dict)
