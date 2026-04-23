"""L1 - Bidder.identity_info_status (honest-detection-results F3)

覆盖 ORM @property + BidderResponse/BidderSummary schema 序列化。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.bidder import Bidder
from app.schemas.bidder import BidderResponse, BidderSummary


# ORM @property 纯逻辑(不需要 DB)


@pytest.mark.parametrize(
    "identity_info,expected",
    [
        (None, "insufficient"),
        ({}, "insufficient"),
        ({"company_full_name": "某某有限公司"}, "sufficient"),
        (
            {
                "company_full_name": "某某",
                "legal_rep": "张三",
                "qualification_no": "AB123",
            },
            "sufficient",
        ),
    ],
)
def test_orm_property(identity_info, expected) -> None:
    b = Bidder(identity_info=identity_info)
    assert b.identity_info_status == expected


# Pydantic schema 从 ORM 实例读字段


def _make_bidder(identity_info) -> Bidder:
    """构造一个 unsaved ORM Bidder 实例,所有必需字段填齐供 schema 序列化。"""
    now = datetime.now(timezone.utc)
    b = Bidder(
        name="B",
        project_id=1,
        parse_status="extracted",
        file_count=0,
        identity_info=identity_info,
    )
    # created_at/updated_at 是 server_default,unsaved 实例上需手填
    b.created_at = now  # type: ignore[assignment]
    b.updated_at = now  # type: ignore[assignment]
    b.id = 1  # type: ignore[assignment]
    return b


def test_bidder_summary_reads_identity_info_status_insufficient() -> None:
    bidder = _make_bidder(None)
    summary = BidderSummary.model_validate(bidder)
    assert summary.identity_info_status == "insufficient"


def test_bidder_summary_reads_identity_info_status_sufficient() -> None:
    bidder = _make_bidder({"company_full_name": "某某"})
    summary = BidderSummary.model_validate(bidder)
    assert summary.identity_info_status == "sufficient"


def test_bidder_response_reads_identity_info_status() -> None:
    bidder = _make_bidder({})
    resp = BidderResponse.model_validate(bidder)
    assert resp.identity_info_status == "insufficient"

    bidder2 = _make_bidder({"company_full_name": "X"})
    resp2 = BidderResponse.model_validate(bidder2)
    assert resp2.identity_info_status == "sufficient"


def test_bidder_summary_json_includes_identity_info_status() -> None:
    """保证前端 JSON 里真的能拿到此字段"""
    bidder = _make_bidder(None)
    dumped = BidderSummary.model_validate(bidder).model_dump()
    assert "identity_info_status" in dumped
    assert dumped["identity_info_status"] == "insufficient"
