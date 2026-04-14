"""L1 单元 - BidderCreate 校验规则 (C4 §10.4)。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.bidder import BidderCreate


def test_normal_name_ok() -> None:
    b = BidderCreate(name="A 公司")
    assert b.name == "A 公司"


def test_strips_whitespace() -> None:
    b = BidderCreate(name="  B 公司  ")
    assert b.name == "B 公司"


def test_empty_rejected() -> None:
    with pytest.raises(ValidationError):
        BidderCreate(name="")


def test_blank_rejected() -> None:
    with pytest.raises(ValidationError):
        BidderCreate(name="   ")


def test_max_length_201_rejected() -> None:
    with pytest.raises(ValidationError):
        BidderCreate(name="x" * 201)


def test_max_length_200_ok() -> None:
    b = BidderCreate(name="x" * 200)
    assert len(b.name) == 200
