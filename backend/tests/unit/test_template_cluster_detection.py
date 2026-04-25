"""L1 - template_cluster._detect_template_cluster 纯函数单测 (CH-2)

覆盖 spec ADD Req "模板簇识别(template cluster detection)" 的 scenario。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.detect.template_cluster import (
    _build_cluster_key,
    _detect_template_cluster,
    _normalize_created_at,
)


def _meta(meta_id: int, author: str | None, created_at: datetime | None):
    return SimpleNamespace(id=meta_id, author=author, doc_created_at=created_at)


# ============================================================ author 归一化


def test_author_normalize_full_width_half_width_case():
    """全角/半角混排 + 大小写经 nfkc_casefold_strip 归一为同一 cluster_key。"""
    dt = datetime(2023, 10, 9, 7, 16, 0, tzinfo=timezone.utc)
    keys = {
        _build_cluster_key("LP", dt),
        _build_cluster_key("ＬＰ", dt),
        _build_cluster_key(" lp ", dt),
        _build_cluster_key("Lp", dt),
    }
    # 全部归一为同一 key
    assert len(keys) == 1


def test_normalize_created_at_naive_treated_as_utc():
    """naive datetime 视 UTC + astimezone(UTC) + 截秒 ISO 字符串。"""
    naive = datetime(2023, 10, 9, 7, 16, 0)
    aware = datetime(2023, 10, 9, 7, 16, 0, tzinfo=timezone.utc)
    assert _normalize_created_at(naive) == _normalize_created_at(aware)


def test_normalize_truncates_microseconds():
    dt1 = datetime(2023, 10, 9, 7, 16, 0, 12345, tzinfo=timezone.utc)
    dt2 = datetime(2023, 10, 9, 7, 16, 0, 99999, tzinfo=timezone.utc)
    assert _normalize_created_at(dt1) == _normalize_created_at(dt2)


def test_normalize_prod_fixture_beijing_to_utc():
    """prod fixture 2023-10-09 07:16:00+08:00 北京 → 2023-10-08T23:16:00+00:00 UTC"""
    from datetime import timedelta

    bj = datetime(2023, 10, 9, 7, 16, 0, tzinfo=timezone(timedelta(hours=8)))
    assert _normalize_created_at(bj) == "2023-10-08T23:16:00+00:00"


# ============================================================ cluster 识别


def test_3_bidder_full_cluster():
    """3 bidder 全同 metadata → 1 cluster bidder_ids=[1,2,3]"""
    dt = datetime(2023, 10, 9, 7, 16, 0, tzinfo=timezone.utc)
    bmap = {
        1: [_meta(101, "LP", dt)],
        2: [_meta(102, "LP", dt)],
        3: [_meta(103, "LP", dt)],
    }
    clusters = _detect_template_cluster(bmap)
    assert len(clusters) == 1
    assert clusters[0].bidder_ids == [1, 2, 3]
    assert clusters[0].cluster_key_sample["author"] == "lp"  # 归一化后小写


def test_2_in_cluster_1_independent():
    dt1 = datetime(2023, 10, 9, 7, 16, 0, tzinfo=timezone.utc)
    dt2 = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    bmap = {
        1: [_meta(101, "LP", dt1)],
        2: [_meta(102, "LP", dt1)],
        3: [_meta(103, "XYZ", dt2)],
    }
    clusters = _detect_template_cluster(bmap)
    assert len(clusters) == 1
    assert clusters[0].bidder_ids == [1, 2]


def test_set_intersection_multi_doc_per_bidder():
    """bidder 多份文档集合相交判簇:S_A={(LP,t1),(LP,t2)}, S_B={(LP,t1)} → 同簇"""
    t1 = datetime(2023, 10, 9, 7, 16, 0, tzinfo=timezone.utc)
    t2 = datetime(2023, 11, 1, 8, 0, 0, tzinfo=timezone.utc)
    bmap = {
        1: [_meta(101, "LP", t1), _meta(102, "LP", t2)],
        2: [_meta(201, "LP", t1)],
    }
    clusters = _detect_template_cluster(bmap)
    assert len(clusters) == 1
    assert clusters[0].bidder_ids == [1, 2]


def test_metadata_author_null_skipped(caplog):
    """metadata author=NULL → 该文档跳过(若该 bidder 其他文档有值仍参与)"""
    dt = datetime(2023, 10, 9, 7, 16, 0, tzinfo=timezone.utc)
    bmap = {
        1: [_meta(101, None, dt), _meta(102, "LP", dt)],
        2: [_meta(201, "LP", dt)],
    }
    with caplog.at_level("WARNING"):
        clusters = _detect_template_cluster(bmap)
    # bidder 1 仍能参与(因 _meta 102 有值)
    assert len(clusters) == 1
    assert clusters[0].bidder_ids == [1, 2]
    # WARNING 日志命中"key incomplete"
    assert any("key incomplete" in r.message for r in caplog.records)


def test_all_metadata_null_returns_empty():
    bmap = {
        1: [_meta(101, None, None)],
        2: [_meta(201, None, None)],
    }
    clusters = _detect_template_cluster(bmap)
    assert clusters == []


def test_aware_vs_naive_treated_as_same_moment():
    """aware vs naive 同瞬间归一化后判同 key"""
    aware = datetime(2023, 10, 9, 7, 16, 0, tzinfo=timezone.utc)
    naive = datetime(2023, 10, 9, 7, 16, 0)  # 视 UTC
    bmap = {
        1: [_meta(101, "LP", aware)],
        2: [_meta(201, "LP", naive)],
    }
    clusters = _detect_template_cluster(bmap)
    assert len(clusters) == 1


def test_all_independent_returns_empty():
    bmap = {
        1: [_meta(101, "A", datetime(2023, 1, 1, tzinfo=timezone.utc))],
        2: [_meta(201, "B", datetime(2024, 1, 1, tzinfo=timezone.utc))],
        3: [_meta(301, "C", datetime(2025, 1, 1, tzinfo=timezone.utc))],
    }
    assert _detect_template_cluster(bmap) == []


def test_single_bidder_returns_empty():
    """1 bidder 项目无法构成跨 bidder 等价类。"""
    dt = datetime(2023, 10, 9, 7, 16, 0, tzinfo=timezone.utc)
    bmap = {1: [_meta(101, "LP", dt)]}
    assert _detect_template_cluster(bmap) == []


def test_transitive_closure_union_find():
    """A-B 同 key1 + B-C 同 key2 → 合并为单簇 [A,B,C](传递闭包)"""
    t1 = datetime(2023, 10, 9, 7, 16, 0, tzinfo=timezone.utc)
    t2 = datetime(2023, 11, 1, 8, 0, 0, tzinfo=timezone.utc)
    bmap = {
        1: [_meta(101, "LP", t1)],
        2: [_meta(201, "LP", t1), _meta(202, "LP", t2)],
        3: [_meta(301, "LP", t2)],
    }
    clusters = _detect_template_cluster(bmap)
    assert len(clusters) == 1
    assert clusters[0].bidder_ids == [1, 2, 3]


def test_stress_n20_all_independent_under_5s():
    """N=20 bidder 全两两不相交 union-find < 5s(round 3 reviewer L4 stress 验证)。"""
    dt_base = datetime(2023, 1, 1, tzinfo=timezone.utc)
    bmap = {
        i: [_meta(100 + i, f"author_{i}", dt_base.replace(month=(i % 12) + 1))]
        for i in range(1, 21)
    }
    t0 = time.perf_counter()
    clusters = _detect_template_cluster(bmap)
    elapsed = time.perf_counter() - t0
    assert clusters == []
    assert elapsed < 5.0
