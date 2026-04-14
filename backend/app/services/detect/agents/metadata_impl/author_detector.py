"""author 维度跨投标人字段聚类碰撞 (C10 metadata_impl)

三子字段:author / last_saved_by / company(NFKC 归一化后精确匹配)。
hit_strength = |∩| / min(|A|, |B|)(偏重"共同占比",优于 Jaccard)。
参与子字段按 AuthorConfig.subdim_weights 重归一化加权 → dim score。

维度级 skip:三子字段均单侧缺失(set_a 或 set_b 全空)→ score=None。
"""

from __future__ import annotations

from app.services.detect.agents.metadata_impl.config import AuthorConfig
from app.services.detect.agents.metadata_impl.models import (
    AuthorDimResult,
    ClusterHit,
    MetadataRecord,
)

_NORM_FIELDS = ("author", "last_saved_by", "company")


def _collect_values(
    records: list[MetadataRecord], field_name: str
) -> tuple[set[str], dict[str, list[int]]]:
    """返 (非空归一化值集合, 值→[doc_ids] 映射)。"""
    norm_key = f"{field_name}_norm"
    values: set[str] = set()
    doc_map: dict[str, list[int]] = {}
    for r in records:
        v = r.get(norm_key)
        if not v:
            continue
        values.add(v)
        doc_map.setdefault(v, []).append(r["bid_document_id"])
    return values, doc_map


def _raw_for(
    records: list[MetadataRecord], field_name: str, norm_val: str
) -> str | None:
    """按归一化值找回首个 raw 原值(展示用)。"""
    raw_key = f"{field_name}_raw"
    norm_key = f"{field_name}_norm"
    for r in records:
        if r.get(norm_key) == norm_val:
            return r.get(raw_key)
    return None


def detect_author_collisions(
    records_a: list[MetadataRecord],
    records_b: list[MetadataRecord],
    cfg: AuthorConfig,
) -> AuthorDimResult:
    """对 author/last_saved_by/company 三子字段跨投标人精确碰撞。"""
    sub_scores: dict[str, float] = {}
    hits: list[ClusterHit] = []
    all_single_side_missing = True

    for field_name in _NORM_FIELDS:
        set_a, doc_map_a = _collect_values(records_a, field_name)
        set_b, doc_map_b = _collect_values(records_b, field_name)
        if not set_a or not set_b:
            # 单侧缺失该子字段 → 不进 sub_scores
            continue
        all_single_side_missing = False
        intersect = set_a & set_b
        if intersect:
            strength = len(intersect) / min(len(set_a), len(set_b))
            sub_scores[field_name] = min(1.0, strength)
            for val in sorted(intersect):
                raw_a = _raw_for(records_a, field_name, val)
                raw_b = _raw_for(records_b, field_name, val)
                hits.append(
                    {
                        "field": field_name,
                        "value": raw_a if raw_a else raw_b if raw_b else val,
                        "normalized": val,
                        "doc_ids_a": doc_map_a[val],
                        "doc_ids_b": doc_map_b[val],
                    }
                )
        else:
            sub_scores[field_name] = 0.0

    if all_single_side_missing:
        return {
            "score": None,
            "reason": "author/last_saved_by/company 三字段均缺失",
            "sub_scores": {},
            "hits": [],
        }

    # 参与子字段的原始权重重归一化
    participating = {k: cfg.subdim_weights.get(k, 0.0) for k in sub_scores}
    total_w = sum(participating.values())
    if total_w <= 0:
        score = 0.0
    else:
        score = sum(
            sub_scores[k] * participating[k] for k in sub_scores
        ) / total_w

    return {
        "score": min(1.0, max(0.0, score)),
        "reason": None,
        "sub_scores": sub_scores,
        "hits": hits[: cfg.max_hits_per_agent],
    }


__all__ = ["detect_author_collisions"]
