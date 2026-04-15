"""L2 - price_consistency Agent 真实检测链路 (C11)

覆盖 execution-plan §3 C11 原 4 Scenario + 本 change Q5 新增 1 Scenario:
1. 尾数完全一致(tail 子检测命中)
2. 报价项明细 95%+ 相同(item_list 子检测命中)
3. 口径不读(currency/tax_inclusive 字段 C11 不读,直接比原始值)
4. 异常样本(NULL total_price)行级 skip 不假阳
5. 等比关系 B = A × 0.95(series 子检测命中,Q5 新增)

策略同 C7~C10:手工构造 ctx 直调 Agent.run() / preflight(不走 engine)。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.bidder import Bidder
from app.models.pair_comparison import PairComparison
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project
from app.models.user import User
from app.services.detect.agents import price_consistency as price_mod
from app.services.detect.context import AgentContext

pytestmark = pytest.mark.asyncio


# ---------- seed helpers ----------


async def _seed_project(owner_id: int) -> tuple[int, int]:
    """返 (project_id, price_parsing_rule_id)."""
    async with async_session() as s:
        p = Project(name="c11-test", status="ready", owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        rule = PriceParsingRule(
            project_id=p.id,
            sheet_name="default",
            header_row=1,
            column_mapping={
                "code_col": "A", "name_col": "B", "unit_col": "C",
                "qty_col": "D", "unit_price_col": "E", "total_price_col": "F",
            },
        )
        s.add(rule)
        await s.commit()
        await s.refresh(rule)
        return p.id, rule.id


async def _seed_bidder(project_id: int, name: str) -> int:
    async with async_session() as s:
        b = Bidder(name=name, project_id=project_id, parse_status="priced")
        s.add(b)
        await s.commit()
        await s.refresh(b)
        return b.id


async def _add_price_items(
    bidder_id: int, rule_id: int, items: list[dict]
) -> None:
    async with async_session() as s:
        for it in items:
            s.add(PriceItem(
                bidder_id=bidder_id,
                price_parsing_rule_id=rule_id,
                sheet_name=it.get("sheet_name", "清单表"),
                row_index=it.get("row_index", 1),
                item_name=it.get("item_name"),
                unit_price=it.get("unit_price"),
                total_price=it.get("total_price"),
            ))
        await s.commit()


async def _run_agent(pid: int, a_id: int, b_id: int):
    async with async_session() as s:
        a = await s.get(Bidder, a_id)
        b = await s.get(Bidder, b_id)
        task = AgentTask(
            project_id=pid,
            version=1,
            agent_name="price_consistency",
            agent_type="pair",
            pair_bidder_a_id=a.id,
            pair_bidder_b_id=b.id,
            status="pending",
        )
        s.add(task)
        await s.flush()
        ctx = AgentContext(
            project_id=pid,
            version=1,
            agent_task=task,
            bidder_a=a,
            bidder_b=b,
            all_bidders=[],
            llm_provider=None,
            session=s,
        )
        result = await price_mod.run(ctx)
        await s.commit()
        return result


async def _load_pc(pid: int, a_id: int, b_id: int) -> PairComparison | None:
    async with async_session() as s:
        stmt = select(PairComparison).where(
            PairComparison.project_id == pid,
            PairComparison.bidder_a_id == a_id,
            PairComparison.bidder_b_id == b_id,
            PairComparison.dimension == "price_consistency",
        )
        return (await s.execute(stmt)).scalar_one_or_none()


# ---------- Scenario 1: 尾数完全一致 ----------


async def test_scenario_tail_collision(clean_users, seeded_reviewer: User):
    """3 行 total_price 尾 3 位都是 "880" 且整数位长同为 6 → tail 子检测命中。"""
    pid, rule_id = await _seed_project(seeded_reviewer.id)
    a = await _seed_bidder(pid, "A")
    b = await _seed_bidder(pid, "B")
    items = [
        {"sheet_name": "清单表", "row_index": i, "item_name": f"x{i}",
         "unit_price": Decimal("100"), "total_price": Decimal(f"1{i:02d}880")}
        for i in range(1, 4)
    ]
    await _add_price_items(a, rule_id, items)
    # B 用相同 total_price
    await _add_price_items(b, rule_id, items)

    result = await _run_agent(pid, a, b)
    assert result.evidence_json["algorithm"] == "price_consistency_v1"
    assert result.evidence_json["enabled"] is True
    assert result.score > 0
    tail_ev = result.evidence_json["subdims"]["tail"]
    assert tail_ev["score"] == 1.0
    assert any(h["tail"] == "880" and h["int_len"] == 6 for h in tail_ev["hits"])
    pc = await _load_pc(pid, a, b)
    assert pc is not None


# ---------- Scenario 2: 报价项明细 95%+ 相同 ----------


async def test_scenario_item_list_high_match(
    clean_users, seeded_reviewer: User
):
    """A/B 同模板 20 行,19 行 (item_name, unit_price) 完全一致 → item_list 命中。"""
    pid, rule_id = await _seed_project(seeded_reviewer.id)
    a = await _seed_bidder(pid, "A")
    b = await _seed_bidder(pid, "B")
    items_a = [
        {"sheet_name": "清单表", "row_index": i, "item_name": f"item{i}",
         "unit_price": Decimal("100"), "total_price": Decimal(f"{i + 100}")}
        for i in range(1, 21)
    ]
    # B 复制 A,只改第 20 行 unit_price(故意 1 行差异)
    items_b = [dict(it) for it in items_a]
    items_b[19]["unit_price"] = Decimal("999")
    await _add_price_items(a, rule_id, items_a)
    await _add_price_items(b, rule_id, items_b)

    result = await _run_agent(pid, a, b)
    item_ev = result.evidence_json["subdims"]["item_list"]
    assert item_ev["score"] is not None and item_ev["score"] >= 0.95
    assert any(h["mode"] == "position" for h in item_ev["hits"])


# ---------- Scenario 3: 口径不读(C11 不消费 currency / tax_inclusive)----------


async def test_scenario_currency_tax_fields_not_read(
    clean_users, seeded_reviewer: User
):
    """两 bidder 无 ProjectPriceConfig 记录 → C11 不报错,直接按 PriceItem 原始数值跑。

    Q2 决策的端到端验证:口径字段不读,无 ProjectPriceConfig 也能正常出结果。
    """
    pid, rule_id = await _seed_project(seeded_reviewer.id)
    a = await _seed_bidder(pid, "A")
    b = await _seed_bidder(pid, "B")
    items = [
        {"row_index": 1, "item_name": "x", "unit_price": Decimal("100"),
         "total_price": Decimal("10000")},
        {"row_index": 2, "item_name": "y", "unit_price": Decimal("50"),
         "total_price": Decimal("5000")},
        {"row_index": 3, "item_name": "z", "unit_price": Decimal("80"),
         "total_price": Decimal("8000")},
    ]
    await _add_price_items(a, rule_id, items)
    await _add_price_items(b, rule_id, items)

    result = await _run_agent(pid, a, b)
    # 不报错 + 正常返回 enabled
    assert "error" not in result.evidence_json
    assert result.evidence_json["enabled"] is True
    # tail 应命中(尾 3 位 "000" 全部 int_len=5)
    assert result.evidence_json["subdims"]["tail"]["score"] is not None


# ---------- Scenario 4: 异常样本行级 skip ----------


async def test_scenario_null_rows_skipped(clean_users, seeded_reviewer: User):
    """部分行 total_price=NULL / item_name=NULL → 该行被各子检测过滤,不假阳。"""
    pid, rule_id = await _seed_project(seeded_reviewer.id)
    a = await _seed_bidder(pid, "A")
    b = await _seed_bidder(pid, "B")
    # A 5 行,3 行 NULL,2 行正常
    items_a = [
        {"row_index": 1, "item_name": None, "total_price": None},
        {"row_index": 2, "item_name": None, "total_price": None},
        {"row_index": 3, "item_name": None, "total_price": None},
        {"row_index": 4, "item_name": "x", "unit_price": Decimal("100"),
         "total_price": Decimal("100")},
        {"row_index": 5, "item_name": "y", "unit_price": Decimal("200"),
         "total_price": Decimal("200")},
    ]
    items_b = [dict(it) for it in items_a]
    await _add_price_items(a, rule_id, items_a)
    await _add_price_items(b, rule_id, items_b)

    result = await _run_agent(pid, a, b)
    assert "error" not in result.evidence_json
    assert result.evidence_json["enabled"] is True
    # tail 子检测:有效行 2 → 都命中
    tail_ev = result.evidence_json["subdims"]["tail"]
    assert tail_ev["score"] is not None
    # NULL 行不应触发 hits 中的虚假 tail key
    for h in tail_ev["hits"]:
        # tail 长度始终 = TAIL_N=3
        assert len(h["tail"]) == 3


# ---------- Scenario 5: 等比关系命中(Q5 新增) ----------


async def test_scenario_series_ratio_match(
    clean_users, seeded_reviewer: User
):
    """B 家每行 total_price = A 对应行 × 0.95 → series 子检测 ratio 命中。"""
    pid, rule_id = await _seed_project(seeded_reviewer.id)
    a = await _seed_bidder(pid, "A")
    b = await _seed_bidder(pid, "B")
    a_vals = [Decimal("10000"), Decimal("20000"), Decimal("30000"),
              Decimal("40000"), Decimal("50000")]
    items_a = [
        {"row_index": i, "item_name": f"x{i}",
         "unit_price": v / Decimal("10"), "total_price": v}
        for i, v in enumerate(a_vals)
    ]
    items_b = [
        {"row_index": i, "item_name": f"x{i}",
         "unit_price": v * Decimal("0.95") / Decimal("10"),
         "total_price": v * Decimal("0.95")}
        for i, v in enumerate(a_vals)
    ]
    await _add_price_items(a, rule_id, items_a)
    await _add_price_items(b, rule_id, items_b)

    result = await _run_agent(pid, a, b)
    series_ev = result.evidence_json["subdims"]["series"]
    assert series_ev["score"] == 1.0
    ratio_hits = [h for h in series_ev["hits"] if h["mode"] == "ratio"]
    assert len(ratio_hits) == 1
    assert ratio_hits[0]["k"] == 0.95
    assert ratio_hits[0]["pairs"] == 5
    # Agent score 至少 series 权重 * 100
    assert result.score >= 20.0  # series weight=0.2 → 至少 20
