"""L1 - error_impl/keyword_extractor (C13)"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.detect.agents.error_impl.config import (
    ErrorConsistencyConfig,
)
from app.services.detect.agents.error_impl.keyword_extractor import (
    extract_keywords,
)


def _bidder(name: str = "甲建设公司", info: dict | None = None):
    return SimpleNamespace(name=name, identity_info=info)


def test_normal_4_field_categories() -> None:
    info = {
        "company_name": "甲建设公司",
        "short_name": "甲公司",
        "key_persons": ["张三", "李四"],
        "credentials": ["AB123", "CD456"],
    }
    cfg = ErrorConsistencyConfig(min_keyword_len=2)
    kws = extract_keywords(_bidder(info=info), cfg)
    assert "甲建设公司" in kws
    assert "甲公司" in kws
    assert "张三" in kws
    assert "李四" in kws
    assert "AB123" in kws


def test_short_word_filtered() -> None:
    info = {"short_name": "甲", "key_persons": ["乙"]}
    cfg = ErrorConsistencyConfig(min_keyword_len=2)
    kws = extract_keywords(_bidder(info=info), cfg)
    assert "甲" not in kws
    assert "乙" not in kws


def test_short_word_len_3_more_strict() -> None:
    info = {"company_name": "甲乙", "credentials": ["AB", "ABC123"]}
    cfg = ErrorConsistencyConfig(min_keyword_len=3)
    kws = extract_keywords(_bidder(info=info), cfg)
    assert "甲乙" not in kws  # len=2 < 3
    assert "AB" not in kws    # len=2 < 3
    assert "ABC123" in kws


def test_downgrade_uses_bidder_name() -> None:
    cfg = ErrorConsistencyConfig(min_keyword_len=2)
    kws = extract_keywords(
        _bidder(name="甲建设公司"), cfg, downgrade=True
    )
    assert kws == ["甲建设公司"]


def test_downgrade_short_name_filtered() -> None:
    cfg = ErrorConsistencyConfig(min_keyword_len=3)
    kws = extract_keywords(_bidder(name="甲"), cfg, downgrade=True)
    assert kws == []


def test_nfkc_normalization() -> None:
    # 全角"AB" 经 NFKC 归一化为半角"AB"
    info = {"credentials": ["ABC", "ABC"]}  # 全角后再加一个半角
    cfg = ErrorConsistencyConfig(min_keyword_len=2)
    kws = extract_keywords(_bidder(info=info), cfg)
    # NFKC 归一化后两者相同 → 去重
    assert kws.count("ABC") == 1


def test_dedup_preserves_order() -> None:
    info = {
        "company_name": "甲公司",
        "short_name": "甲公司",  # 重复
        "key_persons": ["甲公司"],  # 又重复
    }
    cfg = ErrorConsistencyConfig(min_keyword_len=2)
    kws = extract_keywords(_bidder(info=info), cfg)
    assert kws.count("甲公司") == 1


def test_missing_field_no_error() -> None:
    info = {"company_name": "甲"}  # 仅 1 字段
    cfg = ErrorConsistencyConfig(min_keyword_len=2)
    kws = extract_keywords(_bidder(info=info), cfg)
    # 甲 长度=1 < min_len=2 → 过滤
    assert kws == []


def test_none_identity_info_returns_empty() -> None:
    cfg = ErrorConsistencyConfig(min_keyword_len=2)
    kws = extract_keywords(_bidder(info=None), cfg, downgrade=False)
    assert kws == []


def test_list_field_flattened() -> None:
    info = {
        "key_persons": ["张三", "李四", "王五"],
        "credentials": ["AB123", "CD456"],
    }
    cfg = ErrorConsistencyConfig(min_keyword_len=2)
    kws = extract_keywords(_bidder(info=info), cfg)
    assert {"张三", "李四", "王五", "AB123", "CD456"}.issubset(set(kws))
