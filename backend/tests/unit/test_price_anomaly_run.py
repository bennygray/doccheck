"""L1 - price_anomaly.run (C12)

用 monkeypatch + Mock 隔离 extractor/detector,验证 run 的控制流分支:
- ENABLED=false 早返,不调 extractor
- 样本不足 skip 哨兵
- 正常路径命中 outlier
- extractor/detector 异常捕获
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.detect.agents import price_anomaly as pa_mod
from app.services.detect.agents.anomaly_impl.models import (
    BidderPriceSummary,
    DetectionResult,
)
from app.services.detect.context import AgentContext

pytestmark = pytest.mark.asyncio


def _ctx(project_id=1) -> AgentContext:
    return AgentContext(
        project_id=project_id,
        version=1,
        agent_task=None,
        bidder_a=None,
        bidder_b=None,
        all_bidders=[],
        session=None,  # L1 mock,不写 DB
    )


def _summaries(n: int = 5) -> list[BidderPriceSummary]:
    return [
        BidderPriceSummary(
            bidder_id=i + 1,
            bidder_name=f"B{i+1}",
            total_price=100.0 - i * 2.0,
        )
        for i in range(n)
    ]


async def test_run_disabled_early_return_no_extractor(monkeypatch):
    monkeypatch.setenv("PRICE_ANOMALY_ENABLED", "false")
    ext_mock = AsyncMock()
    with patch.object(pa_mod, "aggregate_bidder_totals", ext_mock):
        result = await pa_mod.run(_ctx())
    ext_mock.assert_not_called()
    assert result.score == 0.0
    assert result.evidence_json["enabled"] is False
    assert result.evidence_json["outliers"] == []


async def test_run_normal_with_outlier(monkeypatch):
    monkeypatch.delenv("PRICE_ANOMALY_ENABLED", raising=False)
    monkeypatch.setenv("PRICE_ANOMALY_MIN_SAMPLE_SIZE", "3")
    monkeypatch.setenv("PRICE_ANOMALY_DEVIATION_THRESHOLD", "0.30")

    # 5 家,D 偏低 35%
    fake_summaries = [
        BidderPriceSummary(bidder_id=1, bidder_name="A", total_price=100.0),
        BidderPriceSummary(bidder_id=2, bidder_name="B", total_price=105.0),
        BidderPriceSummary(bidder_id=3, bidder_name="C", total_price=98.0),
        BidderPriceSummary(bidder_id=4, bidder_name="D", total_price=60.0),
        BidderPriceSummary(bidder_id=5, bidder_name="E", total_price=102.0),
    ]
    with patch.object(
        pa_mod,
        "aggregate_bidder_totals",
        AsyncMock(return_value=fake_summaries),
    ):
        result = await pa_mod.run(_ctx())
    ev = result.evidence_json
    assert ev["enabled"] is True
    assert ev["sample_size"] == 5
    assert len(ev["outliers"]) == 1
    assert ev["outliers"][0]["bidder_id"] == 4
    assert ev["outliers"][0]["direction"] == "low"
    assert ev["baseline"] is None
    assert ev["llm_explanation"] is None
    assert ev["participating_subdims"] == ["mean"]
    assert result.score > 0


async def test_run_sample_below_min_skip_sentinel(monkeypatch):
    monkeypatch.delenv("PRICE_ANOMALY_ENABLED", raising=False)
    monkeypatch.setenv("PRICE_ANOMALY_MIN_SAMPLE_SIZE", "3")
    # 仅 2 家(边缘场景:preflight 与 run 间数据变化)
    with patch.object(
        pa_mod,
        "aggregate_bidder_totals",
        AsyncMock(return_value=_summaries(2)),
    ):
        result = await pa_mod.run(_ctx())
    ev = result.evidence_json
    assert result.score == 0.0
    assert ev["participating_subdims"] == []
    assert ev["skip_reason"] == "sample_size_below_min"
    assert ev["outliers"] == []
    assert ev["mean"] is None


async def test_run_no_outliers_normal(monkeypatch):
    monkeypatch.delenv("PRICE_ANOMALY_ENABLED", raising=False)
    monkeypatch.setenv("PRICE_ANOMALY_MIN_SAMPLE_SIZE", "3")
    monkeypatch.setenv("PRICE_ANOMALY_DEVIATION_THRESHOLD", "0.30")

    normal = [
        BidderPriceSummary(bidder_id=i + 1, bidder_name=f"B{i+1}", total_price=100.0)
        for i in range(5)
    ]
    with patch.object(
        pa_mod,
        "aggregate_bidder_totals",
        AsyncMock(return_value=normal),
    ):
        result = await pa_mod.run(_ctx())
    assert result.score == 0.0
    assert result.evidence_json["outliers"] == []
    assert result.evidence_json["sample_size"] == 5


async def test_run_extractor_exception(monkeypatch):
    monkeypatch.delenv("PRICE_ANOMALY_ENABLED", raising=False)
    with patch.object(
        pa_mod,
        "aggregate_bidder_totals",
        AsyncMock(side_effect=RuntimeError("db down")),
    ):
        result = await pa_mod.run(_ctx())
    ev = result.evidence_json
    assert result.score == 0.0
    assert "RuntimeError" in ev["error"]
    assert ev["participating_subdims"] == []


async def test_run_detector_exception(monkeypatch):
    monkeypatch.delenv("PRICE_ANOMALY_ENABLED", raising=False)
    monkeypatch.setenv("PRICE_ANOMALY_MIN_SAMPLE_SIZE", "3")
    with patch.object(
        pa_mod,
        "aggregate_bidder_totals",
        AsyncMock(return_value=_summaries(5)),
    ), patch.object(
        pa_mod,
        "detect_outliers",
        MagicMock(side_effect=ValueError("logic boom")),
    ):
        result = await pa_mod.run(_ctx())
    assert result.score == 0.0
    assert "ValueError" in result.evidence_json["error"]


async def test_run_evidence_config_round_trip(monkeypatch):
    monkeypatch.delenv("PRICE_ANOMALY_ENABLED", raising=False)
    monkeypatch.setenv("PRICE_ANOMALY_MIN_SAMPLE_SIZE", "3")
    monkeypatch.setenv("PRICE_ANOMALY_DEVIATION_THRESHOLD", "0.25")
    with patch.object(
        pa_mod,
        "aggregate_bidder_totals",
        AsyncMock(return_value=_summaries(5)),
    ):
        result = await pa_mod.run(_ctx())
    cfg_dump = result.evidence_json["config"]
    assert cfg_dump["min_sample_size"] == 3
    assert cfg_dump["deviation_threshold"] == 0.25
    assert cfg_dump["direction"] == "low"
