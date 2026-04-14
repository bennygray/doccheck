"""L1 - metadata_impl/author_detector (C10)"""

from __future__ import annotations

from app.services.detect.agents.metadata_impl.author_detector import (
    detect_author_collisions,
)
from app.services.detect.agents.metadata_impl.config import AuthorConfig


def _rec(
    doc_id: int,
    *,
    author: str | None = None,
    last_saved_by: str | None = None,
    company: str | None = None,
    template: str | None = None,
):
    """简化工厂构造 MetadataRecord(归一化字段手动传入)。"""
    return {
        "bid_document_id": doc_id,
        "bidder_id": 1,
        "doc_name": f"d{doc_id}.docx",
        "author_norm": author,
        "last_saved_by_norm": last_saved_by,
        "company_norm": company,
        "template_norm": template,
        "app_name": None,
        "app_version": None,
        "doc_created_at": None,
        "doc_modified_at": None,
        "author_raw": author,
        "last_saved_by_raw": last_saved_by,
        "company_raw": company,
        "template_raw": template,
    }


def _cfg() -> AuthorConfig:
    return AuthorConfig()


def test_all_three_fields_match() -> None:
    records_a = [_rec(1, author="张三", last_saved_by="李四", company="abc")]
    records_b = [_rec(2, author="张三", last_saved_by="李四", company="abc")]
    r = detect_author_collisions(records_a, records_b, _cfg())
    assert r["score"] == 1.0
    assert r["reason"] is None
    assert set(r["sub_scores"].keys()) == {"author", "last_saved_by", "company"}
    assert all(v == 1.0 for v in r["sub_scores"].values())
    fields = {h["field"] for h in r["hits"]}
    assert fields == {"author", "last_saved_by", "company"}


def test_only_author_matches() -> None:
    records_a = [_rec(1, author="张三", last_saved_by="甲", company="a")]
    records_b = [_rec(2, author="张三", last_saved_by="乙", company="b")]
    r = detect_author_collisions(records_a, records_b, _cfg())
    # author 命中 1.0,last_saved_by 命中 0,company 命中 0
    # score = 1.0 * 0.5 + 0 * 0.3 + 0 * 0.2 = 0.5
    assert abs(r["score"] - 0.5) < 1e-6
    assert r["sub_scores"] == {"author": 1.0, "last_saved_by": 0.0, "company": 0.0}


def test_no_match() -> None:
    records_a = [_rec(1, author="甲")]
    records_b = [_rec(2, author="乙")]
    r = detect_author_collisions(records_a, records_b, _cfg())
    assert r["score"] == 0.0
    assert r["sub_scores"] == {"author": 0.0}
    assert r["hits"] == []


def test_single_side_missing_field_skipped() -> None:
    """bidder_a 无 company,bidder_b 有 company → company 不进 sub_scores。"""
    records_a = [_rec(1, author="张三")]  # company=None
    records_b = [_rec(2, author="张三", company="abc")]
    r = detect_author_collisions(records_a, records_b, _cfg())
    assert "company" not in r["sub_scores"]
    # 仅 author 参与,score 重归一化:1.0 * 0.5 / 0.5 = 1.0
    assert r["score"] == 1.0


def test_all_fields_missing_returns_none() -> None:
    records_a = [_rec(1)]  # 三字段全 None
    records_b = [_rec(2)]
    r = detect_author_collisions(records_a, records_b, _cfg())
    assert r["score"] is None
    assert r["reason"] is not None
    assert r["sub_scores"] == {}
    assert r["hits"] == []


def test_hit_strength_min_formula() -> None:
    """bidder_a 3 个 author 都是 '张三',bidder_b 1 个 '张三' → strength=1.0(min=1)。"""
    records_a = [
        _rec(1, author="张三"),
        _rec(2, author="张三"),
        _rec(3, author="张三"),
    ]
    records_b = [_rec(4, author="张三")]
    r = detect_author_collisions(records_a, records_b, _cfg())
    assert r["sub_scores"]["author"] == 1.0


def test_variants_do_not_merge() -> None:
    """'张三' vs '张三 (admin)' 精确不等 → 不命中。"""
    records_a = [_rec(1, author="张三")]
    records_b = [_rec(2, author="张三 (admin)")]
    r = detect_author_collisions(records_a, records_b, _cfg())
    assert r["sub_scores"]["author"] == 0.0


def test_hits_limited_by_max_hits() -> None:
    cfg = AuthorConfig(max_hits_per_agent=2)
    # 3 author 全相同,但 hits 有 3 条相同 normalized?
    # 实际上相同归一化值只命中一条,加多 company/last_saved_by 组合
    records_a = [
        _rec(1, author="a1", last_saved_by="b1", company="c1"),
        _rec(2, author="a2", last_saved_by="b2", company="c2"),
    ]
    records_b = [
        _rec(3, author="a1", last_saved_by="b1", company="c1"),
        _rec(4, author="a2", last_saved_by="b2", company="c2"),
    ]
    r = detect_author_collisions(records_a, records_b, cfg)
    # 三子字段各 2 个命中 → 总 6 条 hits,截断至 2
    assert len(r["hits"]) == 2
