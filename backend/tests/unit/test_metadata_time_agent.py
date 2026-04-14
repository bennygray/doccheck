"""L1 - metadata_time Agent run() (C10)"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.detect.agents import metadata_time
from app.services.detect.context import AgentContext


UTC = timezone.utc


def _make_ctx():
    return AgentContext(
        project_id=1,
        version=1,
        agent_task=SimpleNamespace(id=1),
        bidder_a=SimpleNamespace(id=1, name="A"),
        bidder_b=SimpleNamespace(id=2, name="B"),
        all_bidders=[],
        session=None,
    )


def _rec(doc_id: int, *, modified=None, created=None):
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


@pytest.mark.asyncio
async def test_match_algorithm_in_evidence(monkeypatch):
    base = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    fake_a = [_rec(10, modified=base)]
    fake_b = [_rec(20, modified=base + timedelta(minutes=1))]
    monkeypatch.setattr(
        metadata_time,
        "extract_bidder_metadata",
        AsyncMock(side_effect=[fake_a, fake_b]),
    )
    result = await metadata_time.run(_make_ctx())
    assert result.evidence_json["algorithm"] == "metadata_time_v1"
    assert result.evidence_json["enabled"] is True
    assert result.score > 0


@pytest.mark.asyncio
async def test_dimension_skip(monkeypatch):
    """双方时间字段全空。"""
    fake = [_rec(10)]
    monkeypatch.setattr(
        metadata_time,
        "extract_bidder_metadata",
        AsyncMock(side_effect=[fake, list(fake)]),
    )
    result = await metadata_time.run(_make_ctx())
    assert result.score == 0.0
    assert result.evidence_json["participating_fields"] == []
    assert "元数据缺失" in result.summary


@pytest.mark.asyncio
async def test_flag_disabled(monkeypatch):
    ext = AsyncMock()
    monkeypatch.setattr(metadata_time, "extract_bidder_metadata", ext)
    monkeypatch.setenv("METADATA_TIME_ENABLED", "false")
    result = await metadata_time.run(_make_ctx())
    assert result.score == 0.0
    assert result.evidence_json["enabled"] is False
    ext.assert_not_called()


@pytest.mark.asyncio
async def test_exception_path(monkeypatch):
    monkeypatch.setattr(
        metadata_time,
        "extract_bidder_metadata",
        AsyncMock(side_effect=ValueError("x")),
    )
    result = await metadata_time.run(_make_ctx())
    assert result.score == 0.0
    assert "error" in result.evidence_json
    assert "ValueError" in result.evidence_json["error"]
