"""C9 三维度聚合 + evidence_json 构造。

- 维度级 None(提取失败)→ 不进加权,按实际参与维度原始权重归一化
- 3 维度全 None → score=None,Agent summary="结构缺失"
- is_ironclad:任一维度 sub_score ≥ 0.90 且 Agent score ≥ 85
"""

from __future__ import annotations

from app.services.detect.agents.structure_sim_impl.models import (
    AggregateResult,
    DirResult,
    FieldSimResult,
    FillSimResult,
)

# 维度名(evidence.participating_dimensions 中的字符串)
DIM_DIRECTORY = "directory"
DIM_FIELD = "field_structure"
DIM_FILL = "fill_pattern"

IRONCLAD_SUB_THRESHOLD = 0.90
IRONCLAD_TOTAL_THRESHOLD = 85.0


def aggregate_structure_score(
    dir_r: DirResult | None,
    field_r: FieldSimResult | None,
    fill_r: FillSimResult | None,
    weights: tuple[float, float, float],
) -> AggregateResult:
    """
    3 维度加权(按原始权重归一化)。

    weights: (w_dir, w_field, w_fill);非参与维度权重不计入归一化分母。
    """
    w_dir, w_field, w_fill = weights
    participating: list[str] = []
    total_w = 0.0
    weighted_sum = 0.0

    if dir_r is not None:
        participating.append(DIM_DIRECTORY)
        total_w += w_dir
        weighted_sum += dir_r.score * w_dir
    if field_r is not None:
        participating.append(DIM_FIELD)
        total_w += w_field
        weighted_sum += field_r.score * w_field
    if fill_r is not None:
        participating.append(DIM_FILL)
        total_w += w_fill
        weighted_sum += fill_r.score * w_fill

    if not participating or total_w <= 0:
        return AggregateResult(
            score=None,
            participating_dimensions=[],
            weights_used={},
            is_ironclad=False,
        )

    normalized = weighted_sum / total_w  # 0~1
    score_100 = round(min(100.0, max(0.0, normalized * 100)), 2)

    # is_ironclad:任一参与维度 score ≥ 0.9 且 total ≥ 85
    max_sub = max(
        [
            r.score
            for r in (dir_r, field_r, fill_r)
            if r is not None
        ]
    )
    is_ironclad = (
        max_sub >= IRONCLAD_SUB_THRESHOLD
        and score_100 >= IRONCLAD_TOTAL_THRESHOLD
    )

    weights_used = {}
    if dir_r is not None:
        weights_used[DIM_DIRECTORY] = w_dir
    if field_r is not None:
        weights_used[DIM_FIELD] = w_field
    if fill_r is not None:
        weights_used[DIM_FILL] = w_fill

    return AggregateResult(
        score=score_100,
        participating_dimensions=participating,
        weights_used=weights_used,
        is_ironclad=is_ironclad,
    )


def build_evidence_json(
    dir_r: DirResult | None,
    field_r: FieldSimResult | None,
    fill_r: FillSimResult | None,
    agg: AggregateResult,
    doc_role: str,
    doc_id_a: list[int] | None = None,
    doc_id_b: list[int] | None = None,
    dir_skip_reason: str | None = None,
    field_skip_reason: str | None = None,
    fill_skip_reason: str | None = None,
) -> dict:
    """C9 evidence_json schema(design D9)。"""
    dimensions: dict = {}

    # directory
    if dir_r is not None:
        dimensions[DIM_DIRECTORY] = {
            "score": dir_r.score,
            "reason": None,
            "titles_a_count": dir_r.titles_a_count,
            "titles_b_count": dir_r.titles_b_count,
            "lcs_length": dir_r.lcs_length,
            "sample_titles_matched": list(dir_r.sample_titles_matched),
        }
    else:
        dimensions[DIM_DIRECTORY] = {
            "score": None,
            "reason": dir_skip_reason or "directory_not_extractable",
        }

    # field_structure
    if field_r is not None:
        dimensions[DIM_FIELD] = {
            "score": field_r.score,
            "reason": None,
            "per_sheet": [
                {
                    "sheet_name": s.sheet_name,
                    "header_sim": s.header_sim,
                    "bitmask_sim": s.bitmask_sim,
                    "merged_cells_sim": s.merged_cells_sim,
                    "sub_score": s.sub_score,
                }
                for s in field_r.per_sheet
            ],
        }
    else:
        dimensions[DIM_FIELD] = {
            "score": None,
            "reason": field_skip_reason or "xlsx_sheet_missing",
            "per_sheet": [],
        }

    # fill_pattern
    if fill_r is not None:
        dimensions[DIM_FILL] = {
            "score": fill_r.score,
            "reason": None,
            "per_sheet": [
                {
                    "sheet_name": s.sheet_name,
                    "score": s.score,
                    "matched_pattern_lines": s.matched_pattern_lines,
                    "sample_patterns": list(s.sample_patterns),
                }
                for s in fill_r.per_sheet
            ],
        }
    else:
        dimensions[DIM_FILL] = {
            "score": None,
            "reason": fill_skip_reason or "xlsx_sheet_missing",
            "per_sheet": [],
        }

    return {
        "algorithm": "structure_sim_v1",
        "doc_role": doc_role,
        "doc_id_a": doc_id_a or [],
        "doc_id_b": doc_id_b or [],
        "participating_dimensions": agg.participating_dimensions,
        "weights_used": agg.weights_used,
        "dimensions": dimensions,
    }
