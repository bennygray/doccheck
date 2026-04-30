"""L2 - price_consistency Agent baseline 端到端 (detect-tender-baseline §5.5)

覆盖 spec ADD Req "BOQ 项级 baseline hash" + "4 高优 detector 接入 baseline 注入点"
PC 全链路:
- L1 tender BOQ 命中 → item_list 子检测过滤后 score 降低 / is_ironclad=False
- L2 共识不适用 BOQ 维度(D5,即使 ≥3 家应标方填同一份 BOQ 也不剔除)
- 老路径(无 tender)→ baseline_source='none' + warnings=[],evidence schema 兼容
- L3 ≤2 投标方 + 无 tender → warnings 写入 + 检测照常运行(基线缺失 ≠ 信号无效)

策略:真 DB 路径,seed PriceItem(boq_baseline_hash 直接写入)+ 可选 TenderDocument,
直接调 price_consistency.run()。
"""

from __future__ import annotations

import hashlib
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
from app.models.tender_document import TenderDocument
from app.models.user import User
from app.services.detect.agents import price_consistency as price_mod
from app.services.detect.agents.text_sim_impl.tfidf import _normalize
from app.services.detect.context import AgentContext

pytestmark = pytest.mark.asyncio


def _boq_hash(item_name: str, description: str, unit: str, qty: str) -> str:
    """与 parser fill_price._compute_boq_baseline_hash 口径一致(D5):
    sha256(nfkc_strip(item_name)+'|'+nfkc_strip(description)+'|'+nfkc_strip(unit)+'|'+decimal_normalize(qty))"""
    parts = [_normalize(item_name), _normalize(description), _normalize(unit), str(Decimal(qty).normalize())]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# ============================================================ Seeders


async def _seed_project_with_rule(owner_id: int, tag: str) -> tuple[int, int]:
    async with async_session() as s:
        p = Project(name=f"P_pc_{tag}", status="ready", owner_id=owner_id)
        s.add(p)
        await s.flush()
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
        await s.refresh(p)
        await s.refresh(rule)
        return p.id, rule.id


async def _seed_bidder_with_items(
    project_id: int, rule_id: int, name: str, items: list[dict]
) -> int:
    async with async_session() as s:
        b = Bidder(name=name, project_id=project_id, parse_status="priced")
        s.add(b)
        await s.flush()
        for it in items:
            s.add(
                PriceItem(
                    bidder_id=b.id,
                    price_parsing_rule_id=rule_id,
                    sheet_name=it.get("sheet_name", "清单表"),
                    row_index=it["row_index"],
                    item_name=it.get("item_name"),
                    unit_price=it.get("unit_price"),
                    total_price=it.get("total_price"),
                    boq_baseline_hash=it.get("boq_baseline_hash"),
                )
            )
        await s.commit()
        await s.refresh(b)
        return b.id


async def _seed_tender(
    project_id: int, *, segment_hashes: list[str] | None = None,
    boq_baseline_hashes: list[str] | None = None, tag: str = "pc"
) -> None:
    async with async_session() as s:
        s.add(
            TenderDocument(
                project_id=project_id,
                file_name="模板.zip",
                file_path=f"/tmp/tender_{tag}.zip",
                file_size=4096,
                md5=f"t_{tag}",
                parse_status="extracted",
                segment_hashes=segment_hashes or [],
                boq_baseline_hashes=boq_baseline_hashes or [],
            )
        )
        await s.commit()


async def _run(pid: int, a_id: int, b_id: int) -> PairComparison:
    async with async_session() as s:
        a = await s.get(Bidder, a_id)
        b = await s.get(Bidder, b_id)
        task = AgentTask(
            project_id=pid, version=1, agent_name="price_consistency",
            agent_type="pair", pair_bidder_a_id=a.id, pair_bidder_b_id=b.id,
            status="pending",
        )
        s.add(task)
        await s.flush()
        ctx = AgentContext(
            project_id=pid, version=1, agent_task=task,
            bidder_a=a, bidder_b=b, all_bidders=[],
            llm_provider=None, session=s,
        )
        await price_mod.run(ctx)
        await s.commit()
    async with async_session() as s:
        return (
            await s.execute(
                select(PairComparison).where(
                    PairComparison.project_id == pid,
                    PairComparison.bidder_a_id == a_id,
                    PairComparison.bidder_b_id == b_id,
                    PairComparison.dimension == "price_consistency",
                )
            )
        ).scalar_one()


# 5 个 BOQ 项 fixture(项目名+描述+单位+工程量;不含价格)
BOQ_ITEMS = [
    {"item_name": "建设工程委托监理", "description": "全过程监理", "unit": "项", "qty": "1"},
    {"item_name": "安全监督管理", "description": "施工现场", "unit": "项", "qty": "1"},
    {"item_name": "进度管理服务", "description": "里程碑跟踪", "unit": "月", "qty": "12"},
    {"item_name": "质量管理服务", "description": "全程质量管控", "unit": "项", "qty": "1"},
    {"item_name": "成本管理服务", "description": "预算审计", "unit": "项", "qty": "1"},
]


def _make_items(unit_prices: list[Decimal]) -> list[dict]:
    """构造 PriceItem 入库 dict;每行 boq_baseline_hash 取自 _boq_hash。"""
    rows = []
    for i, (boq, up) in enumerate(zip(BOQ_ITEMS, unit_prices, strict=True)):
        rows.append(
            {
                "row_index": i + 1,
                "item_name": boq["item_name"],
                "unit_price": up,
                "total_price": up * Decimal(boq["qty"]),
                "boq_baseline_hash": _boq_hash(
                    boq["item_name"], boq["description"], boq["unit"], boq["qty"]
                ),
            }
        )
    return rows


# ============================================================ Tests


async def test_l1_tender_boq_match_filters_rows_and_drops_score(
    clean_users, seeded_reviewer: User
):
    """L1 tender BOQ 全部命中 → grouped 全空 → score=0 + is_ironclad=False
    + baseline_source='tender' + baseline_excluded_row_count 标记。"""
    pid, rule_id = await _seed_project_with_rule(seeded_reviewer.id, "l1_tender")
    # A 和 B 用相同单价(强匹配 → 无 baseline 时 score 高 + ironclad)
    same_prices = [Decimal(s) for s in ["100", "200", "150", "180", "120"]]
    a_items = _make_items(same_prices)
    b_items = _make_items(same_prices)
    a_id = await _seed_bidder_with_items(pid, rule_id, "A_l1", a_items)
    b_id = await _seed_bidder_with_items(pid, rule_id, "B_l1", b_items)
    # tender 包含全部 5 个 BOQ hash
    tender_hashes = [r["boq_baseline_hash"] for r in a_items]
    await _seed_tender(pid, boq_baseline_hashes=tender_hashes, tag="l1_tender")

    pc = await _run(pid, a_id, b_id)
    ev = pc.evidence_json
    # baseline 顶级字段
    assert ev["baseline_source"] == "tender"
    assert ev["warnings"] == []
    # 5 行全被剔除
    assert ev["baseline_excluded_row_count"]["bidder_a"] == 5
    assert ev["baseline_excluded_row_count"]["bidder_b"] == 5
    # filter 后无可比对行 → 各子检测 None / 不参与 → score=0
    assert float(pc.score) == 0.0
    assert pc.is_ironclad is False


async def test_l1_tender_boq_partial_match_filtered_score_drops(
    clean_users, seeded_reviewer: User
):
    """部分命中 baseline → 仅剩非 baseline 行参与 detector;score 应低于"全行命中"基线场景。"""
    pid, rule_id = await _seed_project_with_rule(seeded_reviewer.id, "l1_partial")
    same_prices = [Decimal(s) for s in ["100", "200", "150", "180", "120"]]
    a_items = _make_items(same_prices)
    b_items = _make_items(same_prices)
    a_id = await _seed_bidder_with_items(pid, rule_id, "A_par", a_items)
    b_id = await _seed_bidder_with_items(pid, rule_id, "B_par", b_items)
    # tender 仅含前 3 项的 BOQ hash(后 2 项是 vendor 独家)
    tender_hashes = [a_items[i]["boq_baseline_hash"] for i in range(3)]
    await _seed_tender(pid, boq_baseline_hashes=tender_hashes, tag="l1_partial")

    pc = await _run(pid, a_id, b_id)
    ev = pc.evidence_json
    assert ev["baseline_source"] == "tender"
    # 前 3 行(每家)被剔除,后 2 行保留
    assert ev["baseline_excluded_row_count"]["bidder_a"] == 3
    assert ev["baseline_excluded_row_count"]["bidder_b"] == 3
    # 仍有 2 行同价 → item_list 命中,但样本基数小;ironclad 由 score >= threshold 决定
    # 不严格断言具体分数,只验过滤路径生效
    assert "subdims" in ev


async def test_l2_consensus_not_applicable_to_boq(
    clean_users, seeded_reviewer: User
):
    """无 tender + 3 bidders 填同一份 BOQ → BOQ 维度 L2 共识 MUST 不适用(D5),
    baseline_source='none',不剔除任何行(spec scenario "BOQ 跨投标人共识不剔除")。"""
    pid, rule_id = await _seed_project_with_rule(seeded_reviewer.id, "l2_skip")
    # 3 家相同 BOQ + 同单价
    same_prices = [Decimal(s) for s in ["100", "200", "150", "180", "120"]]
    items = _make_items(same_prices)
    a_id = await _seed_bidder_with_items(pid, rule_id, "A_l2", items)
    b_id = await _seed_bidder_with_items(pid, rule_id, "B_l2", items)
    await _seed_bidder_with_items(pid, rule_id, "C_l2", items)
    # **不**建 tender → BOQ 维度 baseline_resolver 直接返 'none'(D5 决策)

    pc = await _run(pid, a_id, b_id)
    ev = pc.evidence_json
    assert ev["baseline_source"] == "none", "BOQ 维度 L2 共识不适用,即使 ≥3 家同 hash 也不剔除"
    assert ev["baseline_excluded_row_count"]["bidder_a"] == 0
    assert ev["baseline_excluded_row_count"]["bidder_b"] == 0
    # 价格全同 → item_list 应有命中(原行为不变)
    assert "subdims" in ev


async def test_no_tender_no_baseline_legacy_behavior(
    clean_users, seeded_reviewer: User
):
    """无 tender + 2 bidders → BOQ 维度不出 L3 警示(BOQ 跳过 L2/L3 共识路径,见 design D5);
    evidence schema 兼容(baseline_source='none' + warnings=[] + 老字段保留)。"""
    pid, rule_id = await _seed_project_with_rule(seeded_reviewer.id, "legacy")
    items = _make_items([Decimal(s) for s in ["100", "200", "150", "180", "120"]])
    a_id = await _seed_bidder_with_items(pid, rule_id, "A_lg", items)
    b_id = await _seed_bidder_with_items(pid, rule_id, "B_lg", items)
    # 无 tender

    pc = await _run(pid, a_id, b_id)
    ev = pc.evidence_json
    assert ev["baseline_source"] == "none"
    # BOQ 维度无 tender 时 baseline_resolver 直接返 none + 无 L3 警示
    assert ev["warnings"] == []
    # 老字段全保留
    assert ev["algorithm"] == "price_consistency_v1"
    assert "subdims" in ev
    assert "doc_ids_a" in ev


async def test_legacy_price_items_without_boq_hash_not_excluded(
    clean_users, seeded_reviewer: User
):
    """老 PriceItem.boq_baseline_hash=NULL 行 + tender 命中部分行 → NULL 行 MUST NOT
    被剔除(向后兼容:老数据不假阳)。"""
    pid, rule_id = await _seed_project_with_rule(seeded_reviewer.id, "legacy_null")
    items = _make_items([Decimal(s) for s in ["100", "200", "150", "180", "120"]])
    # 把后 2 项的 boq_baseline_hash 设为 NULL(模拟老数据)
    items[3]["boq_baseline_hash"] = None
    items[4]["boq_baseline_hash"] = None
    a_id = await _seed_bidder_with_items(pid, rule_id, "A_nl", items)
    b_id = await _seed_bidder_with_items(pid, rule_id, "B_nl", items)
    # tender 包含全部 5 个原 hash(但后 2 项 PriceItem 是 NULL → 不参与匹配)
    tender_hashes = [
        _boq_hash(b["item_name"], b["description"], b["unit"], b["qty"])
        for b in BOQ_ITEMS
    ]
    await _seed_tender(pid, boq_baseline_hashes=tender_hashes, tag="legacy_null")

    pc = await _run(pid, a_id, b_id)
    ev = pc.evidence_json
    # 仅前 3 行被剔除(后 2 行 NULL hash → 跳过)
    assert ev["baseline_excluded_row_count"]["bidder_a"] == 3
    assert ev["baseline_excluded_row_count"]["bidder_b"] == 3
    assert ev["baseline_source"] == "tender"
