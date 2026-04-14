"""machine 维度:(app_name, app_version, template) 三字段元组精确碰撞 (C10 metadata_impl)

三字段任一缺失 → 该 doc 不参与元组匹配(保守避免 "两侧全缺失" 误命中空元组)。
hit_strength = 命中元组覆盖的 doc 数 / 双方总 doc 数(clamp [0, 1])。
"""

from __future__ import annotations

from collections import defaultdict

from app.services.detect.agents.metadata_impl.config import MachineConfig
from app.services.detect.agents.metadata_impl.models import (
    ClusterHit,
    MachineDimResult,
    MetadataRecord,
)


def _key(r: MetadataRecord) -> tuple[str, str, str] | None:
    a = r.get("app_name")
    v = r.get("app_version")
    t = r.get("template_norm")
    if not a or not v or not t:
        return None
    return (a, v, t)


def detect_machine_collisions(
    records_a: list[MetadataRecord],
    records_b: list[MetadataRecord],
    cfg: MachineConfig,
) -> MachineDimResult:
    tuples_a: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    tuples_b: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for r in records_a:
        k = _key(r)
        if k is not None:
            tuples_a[k].append(r["bid_document_id"])
    for r in records_b:
        k = _key(r)
        if k is not None:
            tuples_b[k].append(r["bid_document_id"])

    if not tuples_a or not tuples_b:
        return {
            "score": None,
            "reason": (
                "app_name/app_version/template 三字段构成的完整元组在至少一侧缺失"
            ),
            "hits": [],
        }

    common = set(tuples_a.keys()) & set(tuples_b.keys())
    if not common:
        return {"score": 0.0, "reason": None, "hits": []}

    hits: list[ClusterHit] = []
    for tup in sorted(common):
        hits.append(
            {
                "field": "machine_fingerprint",
                "value": {
                    "app_name": tup[0],
                    "app_version": tup[1],
                    "template": tup[2],
                },
                "doc_ids_a": tuples_a[tup],
                "doc_ids_b": tuples_b[tup],
            }
        )

    hit_doc_count = sum(
        len(tuples_a[t]) + len(tuples_b[t]) for t in common
    )
    total_doc_count = sum(len(v) for v in tuples_a.values()) + sum(
        len(v) for v in tuples_b.values()
    )
    score = (
        min(1.0, hit_doc_count / max(1, total_doc_count))
        if total_doc_count > 0
        else 0.0
    )

    return {
        "score": score,
        "reason": None,
        "hits": hits[: cfg.max_hits_per_agent],
    }


__all__ = ["detect_machine_collisions"]
