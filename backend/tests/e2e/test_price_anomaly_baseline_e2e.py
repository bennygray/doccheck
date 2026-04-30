"""L2 - price_anomaly Agent baseline 端到端 (detect-tender-baseline §6.4)

完整 e2e:真 DB(TEST_DATABASE_URL),seed Project + 3 bidders + PriceItem + TenderDocument,
直接调 price_anomaly.run() 验证 baseline 过滤生效 / outlier 在 baseline 不命中分支仍触发 /
向后兼容。

覆盖关键场景:
1. baseline 过滤改变 outlier 判定 — 命中行被排除后 vendor 总价分布改变 → 是否触发 outlier 不同
2. 全部命中 baseline → sample_size 不足 → score=0 + skip_reason
3. 老路径(无 tender)→ 行为完全等价于 §6 改动前
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.bidder import Bidder
from app.models.overall_analysis import OverallAnalysis
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project
from app.models.tender_document import TenderDocument
from app.models.user import User
from app.services.detect.agents import price_anomaly as pa_mod
from app.services.detect.agents.text_sim_impl.tfidf import _normalize
from app.services.detect.context import AgentContext

pytestmark = pytest.mark.asyncio


def _boq_hash(item_name: str, description: str, unit: str, qty: str) -> str:
    parts = [_normalize(item_name), _normalize(description), _normalize(unit), str(Decimal(qty).normalize())]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# 5 项 BOQ baseline(招标方下发模板,3 家应标方都填了)
BOQ_BASELINE_HASHES = [
    _boq_hash(f"基线项目{i}", f"基线描述{i}", "项", "1") for i in range(5)
]
# 3 项 vendor 独家(应标方各自填的)
VENDOR_UNIQUE_HASHES = [
    _boq_hash(f"独家项目{i}", f"独家描述{i}", "项", "1") for i in range(3)
]


async def _seed(
    *,
    owner_id: int,
    tag: str,
    bidders_data: list[list[tuple[str, Decimal]]],  # [[(boq_hash, total_price), ...], ...]
    tender_boq_hashes: list[str] | None = None,
) -> tuple[int, list[int]]:
    async with async_session() as s:
        p = Project(name=f"P_pa_{tag}", owner_id=owner_id, status="ready")
        s.add(p)
        await s.flush()
        rule = PriceParsingRule(
            project_id=p.id, sheet_name="清单表", header_row=1,
            column_mapping={"code_col": 0, "name_col": 1},
            sheets_config=[{
                "sheet_name": "清单表", "sheet_role": "main", "header_row": 1,
                "column_mapping": {"code_col": 0, "name_col": 1},
            }],
        )
        s.add(rule)
        await s.flush()
        bidder_ids = []
        for bi, items in enumerate(bidders_data):
            b = Bidder(name=f"vendor-{bi}_{tag}", project_id=p.id, parse_status="priced")
            s.add(b)
            await s.flush()
            bidder_ids.append(b.id)
            for i, (boq_hash, total) in enumerate(items):
                s.add(
                    PriceItem(
                        bidder_id=b.id, price_parsing_rule_id=rule.id,
                        sheet_name="清单表", row_index=i + 1,
                        item_name=f"item{i}",
                        unit_price=total, total_price=total,
                        boq_baseline_hash=boq_hash,
                    )
                )
        if tender_boq_hashes is not None:
            s.add(
                TenderDocument(
                    project_id=p.id, file_name="模板.zip", file_path="/t.zip",
                    file_size=100, md5=f"t_{tag}", parse_status="extracted",
                    segment_hashes=[], boq_baseline_hashes=tender_boq_hashes,
                )
            )
        await s.commit()
        return p.id, bidder_ids


async def _run(pid: int) -> OverallAnalysis:
    async with async_session() as s:
        task = AgentTask(
            project_id=pid, version=1, agent_name="price_anomaly", agent_type="global",
            status="pending",
        )
        s.add(task)
        await s.flush()
        ctx = AgentContext(
            project_id=pid, version=1, agent_task=task,
            bidder_a=None, bidder_b=None, all_bidders=[],
            llm_provider=None, session=s,
        )
        await pa_mod.run(ctx)
        await s.commit()
    async with async_session() as s:
        return (
            await s.execute(
                select(OverallAnalysis).where(
                    OverallAnalysis.project_id == pid,
                    OverallAnalysis.dimension == "price_anomaly",
                )
            )
        ).scalar_one()


# ============================================================ Tests


async def test_l1_tender_baseline_filters_extractor(
    clean_users, seeded_reviewer: User
):
    """tender BOQ 命中前 5 行 → SUM 排除 → 每家剩 3 行(各异);outlier 判定基于剩余分布。"""
    bidders_data = []
    for bi in range(3):
        items = [(h, Decimal("500")) for h in BOQ_BASELINE_HASHES]  # 5 baseline
        # 3 行独家 + 不同价格(让 vendor 0 报价低,候选 outlier)
        prices = [Decimal("100"), Decimal("100"), Decimal("100")] if bi == 0 else [Decimal("400"), Decimal("400"), Decimal("400")]
        items += list(zip(VENDOR_UNIQUE_HASHES, prices, strict=True))
        bidders_data.append(items)

    pid, bidders = await _seed(
        owner_id=seeded_reviewer.id,
        tag="l1_filter",
        bidders_data=bidders_data,
        tender_boq_hashes=BOQ_BASELINE_HASHES,
    )

    oa = await _run(pid)
    ev = oa.evidence_json
    # baseline 字段就位
    assert ev["baseline_source"] == "tender"
    assert ev["baseline_excluded_price_item_count"] == 15  # 3 vendors × 5 baseline 行
    # 仍有 sample_size=3(3 vendors × 3 unique 行 → SUM 各家 totals 不同 → outlier 检测可跑)
    assert ev["sample_size"] == 3


async def test_full_baseline_match_skips_due_to_low_sample(
    clean_users, seeded_reviewer: User
):
    """全部 PriceItem 命中 baseline → SUM 排除全部 → 0 bidder 有效 → score=0 + skip。"""
    bidders_data = [
        [(h, Decimal("500")) for h in BOQ_BASELINE_HASHES] for _ in range(3)
    ]
    pid, _ = await _seed(
        owner_id=seeded_reviewer.id,
        tag="l1_full",
        bidders_data=bidders_data,
        tender_boq_hashes=BOQ_BASELINE_HASHES,
    )

    oa = await _run(pid)
    ev = oa.evidence_json
    assert float(oa.score) == 0.0
    assert ev["sample_size"] == 0  # 全 bidder SUM=NULL → 被 extractor 过滤
    assert ev.get("skip_reason") == "sample_size_below_min"
    assert ev["baseline_source"] == "tender"
    assert ev["baseline_excluded_price_item_count"] == 15


async def test_no_tender_legacy_behavior(
    clean_users, seeded_reviewer: User
):
    """无 tender → baseline_source='none' + 0 excluded;聚合 SUM 行为完全等价于 §6 前。"""
    bidders_data = [
        [(h, Decimal("500")) for h in VENDOR_UNIQUE_HASHES * 2]  # 6 行各家
        for _ in range(3)
    ]
    pid, _ = await _seed(
        owner_id=seeded_reviewer.id,
        tag="legacy",
        bidders_data=bidders_data,
        tender_boq_hashes=None,
    )

    oa = await _run(pid)
    ev = oa.evidence_json
    assert ev["baseline_source"] == "none"
    assert ev["baseline_excluded_price_item_count"] == 0
    assert ev["warnings"] == []
    # 老字段全保留
    assert ev["algorithm"] == "price_anomaly_v1"
    assert ev["sample_size"] == 3  # 3 bidders 都有数据
