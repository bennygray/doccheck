"""L1 - price_anomaly baseline 接入(detect-tender-baseline §6.3)

覆盖 spec ADD Req:
- baseline_resolver.get_excluded_price_item_ids:仅命中 tender BOQ hash 的 PriceItem.id
  返集合(BOQ-only;空 tender → 空 set;过滤已软删 bidder + NULL hash)
- 边界 case:全部命中 baseline 时 score 应为 0(从 SUM 排除 → 全 bidder 都没数据 → skip)
- BOQ 维度仅走 L1 tender 路径,L2 共识不适用(D5,baseline_resolver 已保证)

策略:复用 [test_price_anomaly_extractor.py] 的 async_session + clean_tables 模式,
真 DB 验 SQL 行为。
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project
from app.models.tender_document import TenderDocument
from app.models.user import User
from app.services.detect import baseline_resolver
from app.services.detect.agents.text_sim_impl.tfidf import _normalize

pytestmark = pytest.mark.asyncio


def _boq_hash(item_name: str, description: str, unit: str, qty: str) -> str:
    parts = [_normalize(item_name), _normalize(description), _normalize(unit), str(Decimal(qty).normalize())]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


@pytest_asyncio.fixture
async def clean_tables():
    from app.models.agent_task import AgentTask
    from app.models.overall_analysis import OverallAnalysis
    from app.models.pair_comparison import PairComparison
    async def _cleanup():
        async with async_session() as s:
            await s.execute(delete(AgentTask))
            await s.execute(delete(OverallAnalysis))
            await s.execute(delete(PairComparison))
            await s.execute(delete(PriceItem))
            await s.execute(delete(PriceParsingRule))
            await s.execute(delete(BidDocument))
            await s.execute(delete(Bidder))
            await s.execute(delete(TenderDocument))
            await s.execute(delete(Project))
            await s.execute(delete(User))
            await s.commit()
    await _cleanup()
    yield
    await _cleanup()


async def _seed_with_tender(
    *,
    tender_hashes: list[str] | None = None,
    bidders_hashes: list[list[str | None]],
) -> tuple[int, list[int], list[int]]:
    """seed:1 user / 1 project / 1 rule(sheets_config sheet_role=main) /
    每 bidder 5 行 PriceItem(boq_baseline_hash 由 bidders_hashes 指定)/ 可选 tender。

    返 (project_id, bidder_ids, all_price_item_ids)。
    """
    async with async_session() as s:
        u = User(username="anom_baseline", password_hash="x"*60, role="reviewer", is_active=True, must_change_password=False)
        s.add(u); await s.flush()
        p = Project(name="anom_bl_proj", owner_id=u.id, status="ready")
        s.add(p); await s.flush()
        rule = PriceParsingRule(
            project_id=p.id, sheet_name="清单表", header_row=1,
            column_mapping={
                "code_col": 0, "name_col": 1, "unit_col": 2,
                "qty_col": 3, "unit_price_col": 4, "total_price_col": 5,
            },
            sheets_config=[{
                "sheet_name": "清单表", "sheet_role": "main", "header_row": 1,
                "column_mapping": {"code_col": 0, "name_col": 1, "unit_col": 2,
                                   "qty_col": 3, "unit_price_col": 4, "total_price_col": 5},
            }],
        )
        s.add(rule); await s.flush()
        bidder_ids: list[int] = []
        for bi, hashes in enumerate(bidders_hashes):
            b = Bidder(name=f"vendor-{bi}_anom_bl", project_id=p.id, parse_status="priced")
            s.add(b); await s.flush()
            bidder_ids.append(b.id)
            for i, h in enumerate(hashes):
                pi = PriceItem(
                    bidder_id=b.id, price_parsing_rule_id=rule.id,
                    sheet_name="清单表", row_index=i + 1,
                    item_name=f"项目{i+1}",
                    unit_price=Decimal("100"), total_price=Decimal("500"),
                    boq_baseline_hash=h,
                )
                s.add(pi)
        if tender_hashes is not None:
            s.add(TenderDocument(
                project_id=p.id, file_name="模板.zip", file_path="/tmp/t.zip",
                file_size=100, md5="t" * 32, parse_status="extracted",
                segment_hashes=[], boq_baseline_hashes=tender_hashes,
            ))
        await s.commit()
        rows = (await s.execute(select(PriceItem.id).order_by(PriceItem.id))).all()
        return p.id, bidder_ids, [r[0] for r in rows]


# ============================================================ baseline_resolver.get_excluded_price_item_ids


async def test_get_excluded_price_item_ids_no_tender_returns_empty(clean_tables):
    """无 tender → 返空 set(短路保护)。"""
    pid, _, _ = await _seed_with_tender(
        tender_hashes=None,
        bidders_hashes=[["h1", "h2", "h3", "h4", "h5"]],
    )
    async with async_session() as s:
        result = await baseline_resolver.get_excluded_price_item_ids(s, pid)
    assert result == set()


async def test_get_excluded_price_item_ids_tender_with_no_match(clean_tables):
    """tender 含 hash 但 PriceItem 全没命中 → 返空 set。"""
    pid, _, _ = await _seed_with_tender(
        tender_hashes=["h_tender_other"],
        bidders_hashes=[["h_a1", "h_a2", "h_a3", "h_a4", "h_a5"]],
    )
    async with async_session() as s:
        result = await baseline_resolver.get_excluded_price_item_ids(s, pid)
    assert result == set()


async def test_get_excluded_price_item_ids_partial_match(clean_tables):
    """tender 含部分 hash 与 PriceItem 重合 → 仅返命中行 ID。"""
    pid, bidders, pi_ids = await _seed_with_tender(
        tender_hashes=["h_tender_1", "h_tender_2"],
        bidders_hashes=[
            ["h_tender_1", "h_unique_a2", "h_tender_2", "h_unique_a4", "h_unique_a5"],
            ["h_unique_b1", "h_tender_1", "h_unique_b3", "h_unique_b4", "h_tender_2"],
        ],
    )
    async with async_session() as s:
        result = await baseline_resolver.get_excluded_price_item_ids(s, pid)
    # vendor 0:pi_ids[0] (h_tender_1), pi_ids[2] (h_tender_2)
    # vendor 1:pi_ids[6] (h_tender_1), pi_ids[9] (h_tender_2)
    expected = {pi_ids[0], pi_ids[2], pi_ids[6], pi_ids[9]}
    assert result == expected


async def test_get_excluded_price_item_ids_skips_null_hash(clean_tables):
    """boq_baseline_hash NULL 行 → MUST NOT 进结果(老数据兜底)。"""
    pid, _, pi_ids = await _seed_with_tender(
        tender_hashes=["h_t"],
        bidders_hashes=[
            [None, "h_t", None, "h_t", None],  # NULL 行不参与命中
        ],
    )
    async with async_session() as s:
        result = await baseline_resolver.get_excluded_price_item_ids(s, pid)
    # 只有 pi_ids[1] 和 pi_ids[3] 命中(h_t),NULL 行不参与
    assert result == {pi_ids[1], pi_ids[3]}


async def test_get_excluded_price_item_ids_skips_soft_deleted_bidder(clean_tables):
    """软删 bidder 的 PriceItem MUST NOT 进结果(spec 软删过滤)。"""
    from datetime import datetime, timezone
    pid, bidders, pi_ids = await _seed_with_tender(
        tender_hashes=["h_t"],
        bidders_hashes=[
            ["h_t", "h_t"],  # bidder 0 全命中
            ["h_t", "h_t"],  # bidder 1 全命中
        ],
    )
    # 软删 bidder 0
    async with async_session() as s:
        b = await s.get(Bidder, bidders[0])
        b.deleted_at = datetime.now(timezone.utc)
        await s.commit()
    async with async_session() as s:
        result = await baseline_resolver.get_excluded_price_item_ids(s, pid)
    # 仅 bidder 1 的 2 行进结果(pi_ids[2..3])
    assert result == {pi_ids[2], pi_ids[3]}


async def test_get_excluded_price_item_ids_other_project_isolated(clean_tables):
    """其他 project 的 tender / PriceItem MUST NOT 进本 project 结果(数据隔离)。"""
    # seed project 1
    pid_1, bidders_1, pi_ids_1 = await _seed_with_tender(
        tender_hashes=["h_t1"],
        bidders_hashes=[["h_t1"]],
    )
    # seed project 2(独立 user 避免 unique 冲突)
    async with async_session() as s:
        u2 = User(username="anom_bl_p2", password_hash="x"*60, role="reviewer", is_active=True, must_change_password=False)
        s.add(u2); await s.flush()
        p2 = Project(name="anom_bl_p2", owner_id=u2.id, status="ready")
        s.add(p2); await s.flush()
        rule2 = PriceParsingRule(
            project_id=p2.id, sheet_name="清单表", header_row=1,
            column_mapping={"code_col": 0},
            sheets_config=[{"sheet_name": "清单表", "sheet_role": "main", "header_row": 1, "column_mapping": {"code_col": 0}}],
        )
        s.add(rule2); await s.flush()
        b2 = Bidder(name="vendor-p2", project_id=p2.id, parse_status="priced")
        s.add(b2); await s.flush()
        pi2 = PriceItem(
            bidder_id=b2.id, price_parsing_rule_id=rule2.id,
            sheet_name="清单表", row_index=1,
            unit_price=Decimal("100"), total_price=Decimal("500"),
            boq_baseline_hash="h_t1",  # 即使 hash 与 project 1 tender 相同
        )
        s.add(pi2)
        # project 2 没有 tender_documents 行
        await s.commit()

    # 查 project 1 → 仅返 project 1 的 PriceItem
    async with async_session() as s:
        result_1 = await baseline_resolver.get_excluded_price_item_ids(s, pid_1)
    assert result_1 == set(pi_ids_1)

    # 查 project 2 → 空(无 tender)
    async with async_session() as s:
        result_2 = await baseline_resolver.get_excluded_price_item_ids(s, p2.id)
    assert result_2 == set()


# ============================================================ price_anomaly run() integration:全部命中 baseline → score=0


async def test_all_items_baseline_match_drops_score_to_zero(clean_tables, monkeypatch):
    """边界 case:project 全 PriceItem 命中 baseline → SUM 排除全部行 →
    extractor 返 0 bidder → preflight 后被 sample_size_below_min 拦截 → score=0。"""
    from app.services.detect.agents import price_anomaly as pa_mod
    from app.services.detect.agents.anomaly_impl.config import AnomalyConfig
    from app.services.detect.context import AgentContext

    pid, bidders, pi_ids = await _seed_with_tender(
        tender_hashes=["h_t1", "h_t2", "h_t3", "h_t4", "h_t5"],
        bidders_hashes=[
            ["h_t1", "h_t2", "h_t3", "h_t4", "h_t5"],
            ["h_t1", "h_t2", "h_t3", "h_t4", "h_t5"],
            ["h_t1", "h_t2", "h_t3", "h_t4", "h_t5"],
        ],
    )

    # mock load_anomaly_config 返 enabled + min_sample_size=3
    def _cfg():
        return AnomalyConfig(
            enabled=True, min_sample_size=3, deviation_threshold=0.30,
            direction="low", baseline_enabled=False, max_bidders=50, weight=1.0,
        )
    monkeypatch.setattr(pa_mod, "load_anomaly_config", _cfg)

    async with async_session() as s:
        from app.models.agent_task import AgentTask
        task = AgentTask(
            project_id=pid, version=1, agent_name="price_anomaly", agent_type="global",
            status="pending",
        )
        s.add(task); await s.flush()
        ctx = AgentContext(
            project_id=pid, version=1, agent_task=task,
            bidder_a=None, bidder_b=None, all_bidders=[],
            llm_provider=None, session=s,
        )
        result = await pa_mod.run(ctx)
        await s.commit()

    assert result.score == 0.0
    ev = result.evidence_json
    # 全 bidder 命中 baseline → SUM 排除全部 → sample_size 低于 min → skip
    assert ev["sample_size"] < 3
    assert ev.get("skip_reason") == "sample_size_below_min"
    # baseline 字段就位
    assert ev["baseline_source"] == "tender"
    # 15 行(3 bidder × 5 row)全部被 baseline 排除
    assert ev["baseline_excluded_price_item_count"] == 15


async def test_partial_baseline_match_extractor_filters_correctly(clean_tables, monkeypatch):
    """部分行命中 baseline → SUM 排除命中行 → extractor 仍能聚合,score 取决于剩余分布。"""
    from app.services.detect.agents import price_anomaly as pa_mod
    from app.services.detect.agents.anomaly_impl.config import AnomalyConfig
    from app.services.detect.context import AgentContext

    # vendor 0/1/2 各 5 行,前 2 行 hash 命中 tender,后 3 行独立
    pid, bidders, pi_ids = await _seed_with_tender(
        tender_hashes=["h_t1", "h_t2"],
        bidders_hashes=[
            ["h_t1", "h_t2", None, None, None],
            ["h_t1", "h_t2", None, None, None],
            ["h_t1", "h_t2", None, None, None],
        ],
    )

    def _cfg():
        return AnomalyConfig(
            enabled=True, min_sample_size=3, deviation_threshold=0.30,
            direction="low", baseline_enabled=False, max_bidders=50, weight=1.0,
        )
    monkeypatch.setattr(pa_mod, "load_anomaly_config", _cfg)

    async with async_session() as s:
        from app.models.agent_task import AgentTask
        task = AgentTask(
            project_id=pid, version=1, agent_name="price_anomaly", agent_type="global",
            status="pending",
        )
        s.add(task); await s.flush()
        ctx = AgentContext(
            project_id=pid, version=1, agent_task=task,
            bidder_a=None, bidder_b=None, all_bidders=[],
            llm_provider=None, session=s,
        )
        result = await pa_mod.run(ctx)
        await s.commit()

    ev = result.evidence_json
    # 3 bidder × 2 行 = 6 行被 baseline 排除
    assert ev["baseline_excluded_price_item_count"] == 6
    # 仍有 9 行(每 bidder 3 行)参与 SUM,sample_size=3
    assert ev["sample_size"] == 3
    assert ev["baseline_source"] == "tender"
    # 每家剩余 3 行 × 500 = 1500;3 家全相同 → no outlier;score=0(无离群)
    # 但 baseline 字段就位即满足 spec 契约,具体 score 由原 detector 算法决定


async def test_no_baseline_legacy_behavior(clean_tables, monkeypatch):
    """无 tender → baseline_source='none' + 0 行 excluded;其余路径与 §6 改动前完全一致。"""
    from app.services.detect.agents import price_anomaly as pa_mod
    from app.services.detect.agents.anomaly_impl.config import AnomalyConfig
    from app.services.detect.context import AgentContext

    pid, bidders, _ = await _seed_with_tender(
        tender_hashes=None,
        bidders_hashes=[
            [None, None, None, None, None],
            [None, None, None, None, None],
            [None, None, None, None, None],
        ],
    )

    def _cfg():
        return AnomalyConfig(
            enabled=True, min_sample_size=3, deviation_threshold=0.30,
            direction="low", baseline_enabled=False, max_bidders=50, weight=1.0,
        )
    monkeypatch.setattr(pa_mod, "load_anomaly_config", _cfg)

    async with async_session() as s:
        from app.models.agent_task import AgentTask
        task = AgentTask(
            project_id=pid, version=1, agent_name="price_anomaly", agent_type="global",
            status="pending",
        )
        s.add(task); await s.flush()
        ctx = AgentContext(
            project_id=pid, version=1, agent_task=task,
            bidder_a=None, bidder_b=None, all_bidders=[],
            llm_provider=None, session=s,
        )
        result = await pa_mod.run(ctx)
        await s.commit()

    ev = result.evidence_json
    assert ev["baseline_source"] == "none"
    assert ev["baseline_excluded_price_item_count"] == 0
    assert ev["warnings"] == []
    # 老字段全保留(向后兼容)
    assert ev["algorithm"] == "price_anomaly_v1"
    assert ev["sample_size"] == 3
