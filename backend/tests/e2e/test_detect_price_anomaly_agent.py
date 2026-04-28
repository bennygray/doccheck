"""L2 - price_anomaly Agent 真实检测链路 (C12)

覆盖 proposal tasks.md 6.1~6.5 共 5 Scenario:
1. 5 家 priced,1 家偏低 35% → evidence 含 1 outlier,score > 0
2. 2 家 priced(< 3 min) → preflight skip,summary 含 "样本数不足"
3. 5 家全正常 → outliers=[],score=0
4. env DEVIATION_THRESHOLD=0.20 → 偏低 26% 场景变触发
5. env ENABLED=false → evidence enabled=false,outliers=[]

策略贴 C11:手工构造 ctx 直调 Agent.run() / preflight(不走 engine)。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.bidder import Bidder
from app.models.overall_analysis import OverallAnalysis
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project
from app.models.user import User
from app.services.detect.agents import price_anomaly as pa_mod
from app.services.detect.context import AgentContext

pytestmark = pytest.mark.asyncio


async def _seed(
    seeded_reviewer: User, bidder_totals: list[Decimal]
) -> tuple[int, list[int]]:
    """建 project + 多 bidder + 每 bidder 一条 price_item 总价。

    返 (project_id, [bidder_id...]).
    """
    async with async_session() as s:
        p = Project(
            name=f"c12-p-{id(s)}", status="ready", owner_id=seeded_reviewer.id
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)

        # fix-multi-sheet-price-double-count:sheets_config 含 sheet_role='main'
        _cm = {
            "code_col": "A", "name_col": "B", "unit_col": "C",
            "qty_col": "D", "unit_price_col": "E", "total_price_col": "F",
        }
        rule = PriceParsingRule(
            project_id=p.id,
            sheet_name="default",
            header_row=1,
            column_mapping=_cm,
            sheets_config=[{
                "sheet_name": "default",
                "sheet_role": "main",
                "header_row": 1,
                "column_mapping": _cm,
            }],
            status="confirmed",
        )
        s.add(rule)
        await s.flush()

        bidder_ids: list[int] = []
        for i, total in enumerate(bidder_totals):
            b = Bidder(
                name=f"B{i}",
                project_id=p.id,
                parse_status="extracted",
            )
            s.add(b)
            await s.flush()
            bidder_ids.append(b.id)
            pi = PriceItem(
                bidder_id=b.id,
                price_parsing_rule_id=rule.id,
                sheet_name="default",
                row_index=0,
                item_name=f"总报价 B{i}",
                total_price=total,
            )
            s.add(pi)
        await s.commit()
        return p.id, bidder_ids


def _ctx(project_id: int, session) -> AgentContext:
    return AgentContext(
        project_id=project_id,
        version=1,
        agent_task=None,
        bidder_a=None,
        bidder_b=None,
        all_bidders=[],
        session=session,
    )


# ---------- Scenario 1: 5 家,1 家偏低 35% → 命中 1 outlier ----------


async def test_s1_one_outlier_below_35pct(seeded_reviewer, monkeypatch):
    monkeypatch.delenv("PRICE_ANOMALY_ENABLED", raising=False)
    monkeypatch.setenv("PRICE_ANOMALY_MIN_SAMPLE_SIZE", "3")
    monkeypatch.setenv("PRICE_ANOMALY_DEVIATION_THRESHOLD", "0.30")

    pid, bidders = await _seed(
        seeded_reviewer,
        [
            Decimal("100"),
            Decimal("105"),
            Decimal("98"),
            Decimal("60"),  # 偏低 35%(mean=93)
            Decimal("102"),
        ],
    )
    async with async_session() as s:
        ctx = _ctx(pid, s)
        pf = await pa_mod.preflight(ctx)
        assert pf.status == "ok"
        result = await pa_mod.run(ctx)
        await s.commit()

        ev = result.evidence_json
        assert ev["algorithm"] == "price_anomaly_v1"
        assert ev["enabled"] is True
        assert ev["sample_size"] == 5
        assert len(ev["outliers"]) == 1
        assert ev["outliers"][0]["bidder_id"] == bidders[3]
        assert ev["outliers"][0]["direction"] == "low"
        assert result.score > 0

        # 落一行 OverallAnalysis
        oas = (
            await s.execute(
                select(OverallAnalysis).where(
                    OverallAnalysis.project_id == pid,
                    OverallAnalysis.dimension == "price_anomaly",
                )
            )
        ).scalars().all()
        assert len(oas) == 1
        assert float(oas[0].score) > 0


# ---------- Scenario 2: 2 家 priced → preflight skip ----------


async def test_s2_insufficient_sample_preflight_skip(
    seeded_reviewer, monkeypatch
):
    monkeypatch.delenv("PRICE_ANOMALY_ENABLED", raising=False)
    monkeypatch.setenv("PRICE_ANOMALY_MIN_SAMPLE_SIZE", "3")
    pid, _ = await _seed(
        seeded_reviewer, [Decimal("100"), Decimal("105")]
    )
    async with async_session() as s:
        ctx = _ctx(pid, s)
        pf = await pa_mod.preflight(ctx)
    assert pf.status == "skip"
    assert "样本数不足" in pf.reason


# ---------- Scenario 3: 全正常无偏离 ----------


async def test_s3_all_normal_no_outlier(seeded_reviewer, monkeypatch):
    monkeypatch.delenv("PRICE_ANOMALY_ENABLED", raising=False)
    monkeypatch.setenv("PRICE_ANOMALY_MIN_SAMPLE_SIZE", "3")
    monkeypatch.setenv("PRICE_ANOMALY_DEVIATION_THRESHOLD", "0.30")

    pid, _ = await _seed(
        seeded_reviewer,
        [
            Decimal("100"),
            Decimal("105"),
            Decimal("98"),
            Decimal("103"),
            Decimal("102"),
        ],
    )
    async with async_session() as s:
        ctx = _ctx(pid, s)
        result = await pa_mod.run(ctx)
        await s.commit()
    assert result.score == 0.0
    assert result.evidence_json["outliers"] == []
    assert result.evidence_json["sample_size"] == 5


# ---------- Scenario 4: env 阈值 0.20 → 原不触发变触发 ----------


async def test_s4_env_threshold_triggers(seeded_reviewer, monkeypatch):
    monkeypatch.delenv("PRICE_ANOMALY_ENABLED", raising=False)
    monkeypatch.setenv("PRICE_ANOMALY_MIN_SAMPLE_SIZE", "3")
    monkeypatch.setenv("PRICE_ANOMALY_DEVIATION_THRESHOLD", "0.20")

    pid, bidders = await _seed(
        seeded_reviewer,
        [
            Decimal("100"),
            Decimal("105"),
            Decimal("98"),
            Decimal("70"),  # mean=95,偏 -26% — 0.30 阈值下不触发,0.20 触发
            Decimal("102"),
        ],
    )
    async with async_session() as s:
        ctx = _ctx(pid, s)
        result = await pa_mod.run(ctx)
        await s.commit()
    assert len(result.evidence_json["outliers"]) == 1
    assert result.evidence_json["outliers"][0]["bidder_id"] == bidders[3]


# ---------- Scenario 5: ENABLED=false → evidence.enabled=false ----------


async def test_s5_disabled_no_extractor(seeded_reviewer, monkeypatch):
    monkeypatch.setenv("PRICE_ANOMALY_ENABLED", "false")

    pid, _ = await _seed(
        seeded_reviewer,
        [
            Decimal("100"),
            Decimal("60"),
            Decimal("98"),
        ],
    )
    async with async_session() as s:
        ctx = _ctx(pid, s)
        result = await pa_mod.run(ctx)
        await s.commit()
    ev = result.evidence_json
    assert ev["enabled"] is False
    assert ev["outliers"] == []
    assert result.score == 0.0
