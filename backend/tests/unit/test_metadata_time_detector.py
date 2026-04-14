"""L1 - metadata_impl/time_detector (C10)"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.detect.agents.metadata_impl.config import TimeConfig
from app.services.detect.agents.metadata_impl.time_detector import (
    detect_time_collisions,
)


UTC = timezone.utc


def _rec(
    doc_id: int,
    *,
    created: datetime | None = None,
    modified: datetime | None = None,
):
    return {
        "bid_document_id": doc_id,
        "bidder_id": 1,
        "doc_name": f"d{doc_id}",
        "author_norm": None,
        "last_saved_by_norm": None,
        "company_norm": None,
        "template_norm": None,
        "app_name": None,
        "app_version": None,
        "doc_created_at": created,
        "doc_modified_at": modified,
        "author_raw": None,
        "last_saved_by_raw": None,
        "company_raw": None,
        "template_raw": None,
    }


def _cfg() -> TimeConfig:
    return TimeConfig()


def test_modified_within_window_cross_sides() -> None:
    base = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    records_a = [_rec(1, modified=base), _rec(2, modified=base + timedelta(minutes=2))]
    records_b = [
        _rec(3, modified=base + timedelta(minutes=1)),
        _rec(4, modified=base + timedelta(minutes=3)),
    ]
    r = detect_time_collisions(records_a, records_b, _cfg())
    assert r["score"] is not None and r["score"] > 0
    assert r["sub_scores"]["modified_at_cluster"] > 0
    # 一个跨 side 簇覆盖全部 4 个 doc
    dims = [h.get("dimension") for h in r["hits"]]
    assert "modified_at_cluster" in dims


def test_modified_intra_side_only_not_matched() -> None:
    """bidder_a 内部 3 doc 集中修改,bidder_b 远离 → 无跨 side 簇。"""
    base = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    records_a = [
        _rec(1, modified=base),
        _rec(2, modified=base + timedelta(minutes=1)),
        _rec(3, modified=base + timedelta(minutes=2)),
    ]
    records_b = [_rec(4, modified=base + timedelta(hours=2))]
    r = detect_time_collisions(records_a, records_b, _cfg())
    assert r["sub_scores"].get("modified_at_cluster", 0.0) == 0.0


def test_created_at_exact_match() -> None:
    t = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    records_a = [_rec(1, created=t)]
    records_b = [_rec(2, created=t)]
    r = detect_time_collisions(records_a, records_b, _cfg())
    assert r["score"] is not None and r["score"] > 0
    assert r["sub_scores"]["created_at_match"] == 1.0
    assert any(h.get("dimension") == "created_at_match" for h in r["hits"])


def test_both_fields_missing_returns_none() -> None:
    records_a = [_rec(1)]  # 时间字段全 None
    records_b = [_rec(2)]
    r = detect_time_collisions(records_a, records_b, _cfg())
    assert r["score"] is None
    assert r["reason"] is not None


def test_window_config_effective() -> None:
    """修改时间差 10 分钟,默认 5 分钟窗不命中,传 15 分钟窗命中。"""
    base = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    records_a = [_rec(1, modified=base)]
    records_b = [_rec(2, modified=base + timedelta(minutes=10))]
    r_narrow = detect_time_collisions(records_a, records_b, TimeConfig(window_min=5))
    assert r_narrow["sub_scores"].get("modified_at_cluster", 0.0) == 0.0
    r_wide = detect_time_collisions(records_a, records_b, TimeConfig(window_min=15))
    assert r_wide["sub_scores"].get("modified_at_cluster", 0.0) > 0


def test_only_modified_available() -> None:
    base = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    records_a = [_rec(1, modified=base)]
    records_b = [_rec(2, modified=base + timedelta(minutes=1))]
    r = detect_time_collisions(records_a, records_b, _cfg())
    assert "created_at_match" not in r["sub_scores"]
    assert "modified_at_cluster" in r["sub_scores"]
