"""L1 - metadata_impl/normalizer (C10)"""

from __future__ import annotations

from app.services.detect.agents.metadata_impl.normalizer import (
    nfkc_casefold_strip,
)


def test_none_returns_none() -> None:
    assert nfkc_casefold_strip(None) is None


def test_empty_and_whitespace_returns_none() -> None:
    assert nfkc_casefold_strip("") is None
    assert nfkc_casefold_strip("   ") is None
    assert nfkc_casefold_strip("\t\n") is None


def test_fullwidth_ascii_to_halfwidth() -> None:
    assert nfkc_casefold_strip("ＺＨＡＮＧ Ｓａｎ") == "zhang san"


def test_casefold_and_strip() -> None:
    assert nfkc_casefold_strip("  张三  ") == "张三"
    assert nfkc_casefold_strip("Normal.DOTM") == "normal.dotm"


def test_mixed_case_whitespace() -> None:
    assert nfkc_casefold_strip(" Microsoft Office Word \n") == "microsoft office word"
