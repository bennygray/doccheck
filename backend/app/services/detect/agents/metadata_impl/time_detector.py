"""time 维度:modified_at 滑窗聚集 + created_at 精确相等 (C10 metadata_impl)

两子信号独立判定:
1. modified_at 滑窗:合并双方所有 (modified_at, doc_id, side),按时间排序,
   任何连续 2+ 条 ≤ window 且跨 side → 记一条 cluster
2. created_at 精确相等:按值分组,共同时间点命中

参与子信号按 TimeConfig.subdim_weights 重归一化加权为 dim score。
双方双字段都无 → score=None。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from app.services.detect.agents.metadata_impl.config import TimeConfig
from app.services.detect.agents.metadata_impl.models import (
    MetadataRecord,
    TimeCluster,
    TimeDimResult,
)


def _slide_window_clusters(
    mods_a: list[tuple[datetime, int]],
    mods_b: list[tuple[datetime, int]],
    window_min: int,
) -> tuple[float, list[TimeCluster]]:
    """双指针扫描,找跨 side 的 ≤ window 分钟簇。"""
    if not mods_a or not mods_b:
        return 0.0, []
    window = timedelta(minutes=window_min)
    all_items = (
        [(t, d, "a") for t, d in mods_a]
        + [(t, d, "b") for t, d in mods_b]
    )
    all_items.sort(key=lambda x: x[0])

    clusters: list[TimeCluster] = []
    n = len(all_items)
    i = 0
    while i < n:
        j = i + 1
        while j < n and (all_items[j][0] - all_items[i][0]) <= window:
            j += 1
        # [i, j) 区间
        if j - i >= 2:
            sides = {all_items[k][2] for k in range(i, j)}
            if sides == {"a", "b"}:
                clusters.append(
                    {
                        "dimension": "modified_at_cluster",
                        "window_min": window_min,
                        "doc_ids_a": [
                            all_items[k][1]
                            for k in range(i, j)
                            if all_items[k][2] == "a"
                        ],
                        "doc_ids_b": [
                            all_items[k][1]
                            for k in range(i, j)
                            if all_items[k][2] == "b"
                        ],
                        "times": [
                            all_items[k][0].isoformat() for k in range(i, j)
                        ],
                    }
                )
                # 跳过整个簇,避免重复
                i = j
                continue
        i += 1

    if not clusters:
        return 0.0, []
    hit_doc_count = sum(
        len(c["doc_ids_a"]) + len(c["doc_ids_b"]) for c in clusters
    )
    total = len(mods_a) + len(mods_b)
    return min(1.0, hit_doc_count / max(1, total)), clusters


def _created_at_matches(
    records_a: list[MetadataRecord], records_b: list[MetadataRecord]
) -> tuple[float, list[TimeCluster]]:
    map_a: dict[datetime, list[int]] = defaultdict(list)
    map_b: dict[datetime, list[int]] = defaultdict(list)
    for r in records_a:
        if r.get("doc_created_at"):
            map_a[r["doc_created_at"]].append(r["bid_document_id"])
    for r in records_b:
        if r.get("doc_created_at"):
            map_b[r["doc_created_at"]].append(r["bid_document_id"])
    if not map_a or not map_b:
        return 0.0, []
    common = set(map_a.keys()) & set(map_b.keys())
    if not common:
        return 0.0, []
    clusters: list[TimeCluster] = []
    for t in sorted(common):
        clusters.append(
            {
                "dimension": "created_at_match",
                "doc_ids_a": map_a[t],
                "doc_ids_b": map_b[t],
                "times": [t.isoformat()],
            }
        )
    hit = sum(len(map_a[t]) + len(map_b[t]) for t in common)
    total = sum(len(v) for v in map_a.values()) + sum(
        len(v) for v in map_b.values()
    )
    return min(1.0, hit / max(1, total)), clusters


def detect_time_collisions(
    records_a: list[MetadataRecord],
    records_b: list[MetadataRecord],
    cfg: TimeConfig,
) -> TimeDimResult:
    mods_a = [
        (r["doc_modified_at"], r["bid_document_id"])
        for r in records_a
        if r.get("doc_modified_at")
    ]
    mods_b = [
        (r["doc_modified_at"], r["bid_document_id"])
        for r in records_b
        if r.get("doc_modified_at")
    ]
    modified_available = bool(mods_a and mods_b)
    created_available = any(r.get("doc_created_at") for r in records_a) and any(
        r.get("doc_created_at") for r in records_b
    )

    if not modified_available and not created_available:
        return {
            "score": None,
            "reason": "doc_modified_at / doc_created_at 字段全缺失",
            "sub_scores": {},
            "hits": [],
        }

    sub_scores: dict[str, float] = {}
    hits: list[TimeCluster] = []

    if modified_available:
        s1, clusters1 = _slide_window_clusters(
            mods_a, mods_b, cfg.window_min
        )
        sub_scores["modified_at_cluster"] = s1
        hits.extend(clusters1)

    if created_available:
        s2, clusters2 = _created_at_matches(records_a, records_b)
        sub_scores["created_at_match"] = s2
        hits.extend(clusters2)

    # 参与子信号的权重重归一化
    participating = {
        k: cfg.subdim_weights.get(k, 0.0) for k in sub_scores
    }
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


__all__ = ["detect_time_collisions"]
