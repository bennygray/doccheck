"""L1 - metadata_author Agent run() (C10)"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.detect.agents import metadata_author
from app.services.detect.context import AgentContext


def _make_ctx():
    """AgentContext 不走 DB:session=None → write_pair_comparison_row 静默。"""
    return AgentContext(
        project_id=1,
        version=1,
        agent_task=SimpleNamespace(id=1),
        bidder_a=SimpleNamespace(id=1, name="A"),
        bidder_b=SimpleNamespace(id=2, name="B"),
        all_bidders=[],
        session=None,
    )


@pytest.mark.asyncio
async def test_algorithm_in_evidence_on_match(monkeypatch):
    # mock extractor 返 2 bidder 都有 author="张三"
    fake_a = [
        {
            "bid_document_id": 10,
            "bidder_id": 1,
            "doc_name": "a",
            "author_norm": "张三",
            "last_saved_by_norm": None,
            "company_norm": None,
            "template_norm": None,
            "app_name": None,
            "app_version": None,
            "doc_created_at": None,
            "doc_modified_at": None,
            "author_raw": "张三",
            "last_saved_by_raw": None,
            "company_raw": None,
            "template_raw": None,
        }
    ]
    fake_b = [dict(fake_a[0]) | {"bid_document_id": 20, "bidder_id": 2, "doc_name": "b"}]
    monkeypatch.setattr(
        metadata_author,
        "extract_bidder_metadata",
        AsyncMock(side_effect=[fake_a, fake_b]),
    )
    result = await metadata_author.run(_make_ctx())
    assert result.evidence_json["algorithm"] == "metadata_author_v1"
    assert result.evidence_json["enabled"] is True
    assert "author" in result.evidence_json["participating_fields"]
    assert result.score > 0


@pytest.mark.asyncio
async def test_dimension_skip_participating_empty(monkeypatch):
    """两侧所有 3 字段全 None → 维度级 skip。"""
    empty = [
        {
            "bid_document_id": 10,
            "bidder_id": 1,
            "doc_name": "a",
            "author_norm": None,
            "last_saved_by_norm": None,
            "company_norm": None,
            "template_norm": None,
            "app_name": None,
            "app_version": None,
            "doc_created_at": None,
            "doc_modified_at": None,
            "author_raw": None,
            "last_saved_by_raw": None,
            "company_raw": None,
            "template_raw": None,
        }
    ]
    monkeypatch.setattr(
        metadata_author,
        "extract_bidder_metadata",
        AsyncMock(side_effect=[empty, list(empty)]),
    )
    result = await metadata_author.run(_make_ctx())
    assert result.score == 0.0
    assert result.evidence_json["participating_fields"] == []
    assert result.evidence_json["enabled"] is True
    assert "元数据缺失" in result.summary


@pytest.mark.asyncio
async def test_flag_disabled_extractor_not_called(monkeypatch):
    ext_mock = AsyncMock()
    monkeypatch.setattr(metadata_author, "extract_bidder_metadata", ext_mock)
    monkeypatch.setenv("METADATA_AUTHOR_ENABLED", "false")
    result = await metadata_author.run(_make_ctx())
    assert result.score == 0.0
    assert result.evidence_json["enabled"] is False
    assert "禁用" in result.summary
    ext_mock.assert_not_called()


@pytest.mark.asyncio
async def test_exception_writes_error_evidence(monkeypatch):
    monkeypatch.setattr(
        metadata_author,
        "extract_bidder_metadata",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    result = await metadata_author.run(_make_ctx())
    assert result.score == 0.0
    assert "error" in result.evidence_json
    assert "RuntimeError" in result.evidence_json["error"]
    assert "执行失败" in result.summary
