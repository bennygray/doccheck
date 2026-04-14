"""L1 - metadata_machine Agent run() (C10)"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.detect.agents import metadata_machine
from app.services.detect.context import AgentContext


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


def _rec(doc_id: int, *, app_name=None, app_version=None, template=None):
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


@pytest.mark.asyncio
async def test_match_ironclad(monkeypatch):
    fake_a = [_rec(10, app_name="word", app_version="16.0", template="normal.dotm")]
    fake_b = [_rec(20, app_name="word", app_version="16.0", template="normal.dotm")]
    monkeypatch.setattr(
        metadata_machine,
        "extract_bidder_metadata",
        AsyncMock(side_effect=[fake_a, fake_b]),
    )
    result = await metadata_machine.run(_make_ctx())
    assert result.evidence_json["algorithm"] == "metadata_machine_v1"
    assert result.score >= 85.0
    assert "machine_fingerprint" in result.evidence_json["participating_fields"]


@pytest.mark.asyncio
async def test_no_match_score_zero(monkeypatch):
    fake_a = [_rec(10, app_name="word", app_version="16.0", template="x.dotm")]
    fake_b = [_rec(20, app_name="word", app_version="16.0", template="y.dotx")]
    monkeypatch.setattr(
        metadata_machine,
        "extract_bidder_metadata",
        AsyncMock(side_effect=[fake_a, fake_b]),
    )
    result = await metadata_machine.run(_make_ctx())
    assert result.score == 0.0


@pytest.mark.asyncio
async def test_dimension_skip(monkeypatch):
    """一侧三字段元组全缺失。"""
    fake_a = [_rec(10, app_name="word", template=None)]  # 缺 version
    fake_b = [_rec(20, app_name="word", app_version="16.0", template="x")]
    monkeypatch.setattr(
        metadata_machine,
        "extract_bidder_metadata",
        AsyncMock(side_effect=[fake_a, fake_b]),
    )
    result = await metadata_machine.run(_make_ctx())
    assert result.score == 0.0
    assert result.evidence_json["participating_fields"] == []


@pytest.mark.asyncio
async def test_flag_disabled(monkeypatch):
    ext = AsyncMock()
    monkeypatch.setattr(metadata_machine, "extract_bidder_metadata", ext)
    monkeypatch.setenv("METADATA_MACHINE_ENABLED", "false")
    result = await metadata_machine.run(_make_ctx())
    assert result.score == 0.0
    assert result.evidence_json["enabled"] is False
    ext.assert_not_called()


@pytest.mark.asyncio
async def test_exception_path(monkeypatch):
    monkeypatch.setattr(
        metadata_machine,
        "extract_bidder_metadata",
        AsyncMock(side_effect=KeyError("k")),
    )
    result = await metadata_machine.run(_make_ctx())
    assert result.score == 0.0
    assert "KeyError" in result.evidence_json["error"]
