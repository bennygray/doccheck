"""L1 - metadata_impl/machine_detector (C10)"""

from __future__ import annotations

from app.services.detect.agents.metadata_impl.config import MachineConfig
from app.services.detect.agents.metadata_impl.machine_detector import (
    detect_machine_collisions,
)


def _rec(
    doc_id: int,
    *,
    app_name: str | None = None,
    app_version: str | None = None,
    template: str | None = None,
):
    return {
        "bid_document_id": doc_id,
        "bidder_id": 1,
        "doc_name": f"d{doc_id}",
        "author_norm": None,
        "last_saved_by_norm": None,
        "company_norm": None,
        "template_norm": template,
        "app_name": app_name,
        "app_version": app_version,
        "doc_created_at": None,
        "doc_modified_at": None,
        "author_raw": None,
        "last_saved_by_raw": None,
        "company_raw": None,
        "template_raw": template,
    }


def _cfg() -> MachineConfig:
    return MachineConfig()


def test_tuple_exact_match() -> None:
    records_a = [
        _rec(1, app_name="word", app_version="16.0", template="normal.dotm"),
        _rec(2, app_name="word", app_version="16.0", template="normal.dotm"),
    ]
    records_b = [
        _rec(3, app_name="word", app_version="16.0", template="normal.dotm"),
    ]
    r = detect_machine_collisions(records_a, records_b, _cfg())
    assert r["score"] == 1.0  # 全部 3 doc 都命中同一元组
    assert len(r["hits"]) == 1
    h = r["hits"][0]
    assert h["field"] == "machine_fingerprint"
    assert h["value"]["app_name"] == "word"
    assert h["value"]["template"] == "normal.dotm"


def test_one_field_differs_no_match() -> None:
    records_a = [
        _rec(1, app_name="word", app_version="16.0", template="normal.dotm")
    ]
    records_b = [
        _rec(2, app_name="word", app_version="16.0", template="custom.dotx")
    ]
    r = detect_machine_collisions(records_a, records_b, _cfg())
    assert r["score"] == 0.0
    assert r["hits"] == []


def test_one_field_missing_all_records_excluded() -> None:
    """bidder_a 所有 doc template=None → tuples_a 空 → 维度 skip。"""
    records_a = [_rec(1, app_name="word", app_version="16.0", template=None)]
    records_b = [_rec(2, app_name="word", app_version="16.0", template="x")]
    r = detect_machine_collisions(records_a, records_b, _cfg())
    assert r["score"] is None
    assert r["reason"] is not None


def test_partial_doc_incomplete_tuple() -> None:
    """bidder_a 3 doc,仅 1 个三字段齐全且与 bidder_b 命中。"""
    records_a = [
        _rec(1, app_name=None, app_version="16.0", template="x"),  # 缺 app_name
        _rec(2, app_name="word", app_version=None, template="x"),  # 缺 app_version
        _rec(3, app_name="word", app_version="16.0", template="x"),  # 完整
    ]
    records_b = [_rec(4, app_name="word", app_version="16.0", template="x")]
    r = detect_machine_collisions(records_a, records_b, _cfg())
    # 仅 doc 3 参与;命中 1 doc_a + 1 doc_b,总 tuples_* 元素也只 1+1=2
    # hit_strength = 2 / 2 = 1.0
    assert r["score"] == 1.0
    assert len(r["hits"]) == 1
    assert r["hits"][0]["doc_ids_a"] == [3]
    assert r["hits"][0]["doc_ids_b"] == [4]


def test_both_sides_empty_tuples() -> None:
    records_a = [_rec(1)]  # 全 None
    records_b = [_rec(2)]
    r = detect_machine_collisions(records_a, records_b, _cfg())
    assert r["score"] is None
    assert r["reason"] is not None
