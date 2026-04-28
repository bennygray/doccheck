"""L2 — fix-multi-sheet-price-double-count 三场景 e2e。

直接在真实 DB 上验证:
1. 监理标场景:LLM 标 main+breakdown → aggregate 仅 SUM main
2. 工程量清单场景:多 sheet 全 main → aggregate SUM 全部
3. LLM 错兜底:LLM 全标 main + SUM 相等 → F validator 修正

不走 pipeline.run_pipeline(避免 LLM 调用),直接 seed + 调用 aggregator/validator。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.session import async_session
from app.models.bidder import Bidder
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project
from app.models.user import User
from app.services.detect.agents.anomaly_impl.config import AnomalyConfig
from app.services.detect.agents.anomaly_impl.extractor import (
    aggregate_bidder_totals,
)
from app.services.parser.pipeline.sheet_role_validator import validate_sheet_roles

pytestmark = pytest.mark.asyncio


def _cfg() -> AnomalyConfig:
    return AnomalyConfig(
        enabled=True,
        min_sample_size=3,
        deviation_threshold=0.30,
        direction="low",
        baseline_enabled=False,
        max_bidders=50,
        weight=1.0,
    )


@pytest_asyncio.fixture
async def clean_tables():
    async with async_session() as s:
        await s.execute(delete(PriceItem))
        await s.execute(delete(PriceParsingRule))
        await s.execute(delete(Bidder))
        await s.execute(delete(Project))
        await s.execute(delete(User))
        await s.commit()
    yield
    async with async_session() as s:
        await s.execute(delete(PriceItem))
        await s.execute(delete(PriceParsingRule))
        await s.execute(delete(Bidder))
        await s.execute(delete(Project))
        await s.execute(delete(User))
        await s.commit()


async def _seed_project_with_rule(
    sheets_config: list[dict],
    bidder_specs: list[tuple[str, list[tuple[str, Decimal]]]],
) -> tuple[int, int]:
    """Seed project + rule + bidder + price_items.

    bidder_specs: list of (bidder_name, [(sheet_name, total_price), ...])
    Returns (project_id, rule_id)
    """
    async with async_session() as s:
        u = User(username=f"u_{id(s)}", password_hash="x", role="reviewer")
        s.add(u); await s.flush()
        p = Project(name="multisheet_test", owner_id=u.id)
        s.add(p); await s.flush()

        rule = PriceParsingRule(
            project_id=p.id,
            sheet_name=sheets_config[0]["sheet_name"],
            header_row=1,
            column_mapping={
                "code_col": "A", "name_col": "B", "unit_col": "C",
                "qty_col": "D", "unit_price_col": "E", "total_price_col": "F",
            },
            sheets_config=sheets_config,
            status="confirmed",
        )
        s.add(rule); await s.flush()

        for bname, items in bidder_specs:
            b = Bidder(name=bname, project_id=p.id, parse_status="extracted")
            s.add(b); await s.flush()
            for idx, (sn, tp) in enumerate(items):
                s.add(PriceItem(
                    bidder_id=b.id,
                    price_parsing_rule_id=rule.id,
                    sheet_name=sn,
                    row_index=idx,
                    item_name=f"项{idx}",
                    total_price=tp,
                ))
            await s.flush()
        await s.commit()
        return p.id, rule.id


async def test_monitoring_template_scenario_llm_correct_main_breakdown(clean_tables):
    """监理标:LLM 标 main + breakdown 正确 → aggregate 仅 SUM main(456000 而非 912000)."""
    sheets_config = [
        {"sheet_name": "报价表", "sheet_role": "main"},
        {"sheet_name": "管理人员单价表", "sheet_role": "breakdown"},
    ]
    pid, _ = await _seed_project_with_rule(
        sheets_config,
        [
            ("供A", [
                ("报价表", Decimal("456000")),  # main
                ("管理人员单价表", Decimal("150000")),  # breakdown 不计入
                ("管理人员单价表", Decimal("90000")),
                ("管理人员单价表", Decimal("60000")),
                ("管理人员单价表", Decimal("90000")),
                ("管理人员单价表", Decimal("66000")),
            ]),
        ],
    )
    async with async_session() as s:
        summaries = await aggregate_bidder_totals(s, pid, _cfg())
    assert len(summaries) == 1
    assert summaries[0]["total_price"] == 456000.0  # 不是 912000(2x)


async def test_boq_scenario_all_main_sums_independently(clean_tables):
    """工程量清单:三 sheet 全 main → aggregate SUM = 各 sheet sum 之和."""
    sheets_config = [
        {"sheet_name": "土建", "sheet_role": "main"},
        {"sheet_name": "安装", "sheet_role": "main"},
        {"sheet_name": "电气", "sheet_role": "main"},
    ]
    pid, _ = await _seed_project_with_rule(
        sheets_config,
        [
            ("供A", [
                ("土建", Decimal("100000")),
                ("安装", Decimal("200000")),
                ("电气", Decimal("50000")),
            ]),
        ],
    )
    async with async_session() as s:
        summaries = await aggregate_bidder_totals(s, pid, _cfg())
    assert summaries[0]["total_price"] == 350000.0


async def test_llm_misclassify_then_validator_fixes(clean_tables):
    """LLM 全标 main + 两 sheet SUM 相等 → F validator 把多行的改 breakdown."""
    # 模拟 LLM 误判:都 main
    sheets_config = [
        {"sheet_name": "主表", "sheet_role": "main"},
        {"sheet_name": "明细", "sheet_role": "main"},
    ]
    pid, rid = await _seed_project_with_rule(
        sheets_config,
        [
            ("供A", [
                ("主表", Decimal("456000")),  # 1 row
                ("明细", Decimal("150000")),
                ("明细", Decimal("90000")),
                ("明细", Decimal("60000")),
                ("明细", Decimal("90000")),
                ("明细", Decimal("66000")),  # 5 rows SUM=456000
            ]),
        ],
    )

    # 在 aggregate 之前先跑 validator 修正
    async with async_session() as s:
        items = (await s.execute(
            __import__("sqlalchemy").select(PriceItem).where(PriceItem.bidder_id.in_(
                __import__("sqlalchemy").select(Bidder.id).where(Bidder.project_id == pid).scalar_subquery()
            ))
        )).scalars().all()

    fixed, decisions = validate_sheet_roles(sheets_config, items)
    assert len(decisions) == 1
    by_name = {x["sheet_name"]: x for x in fixed}
    assert by_name["主表"]["sheet_role"] == "main"  # 行数少 (1) → main
    assert by_name["明细"]["sheet_role"] == "breakdown"  # 行数多 (5) → breakdown

    # 持久化 fixed → DB
    from sqlalchemy.orm.attributes import flag_modified
    async with async_session() as s:
        rule = await s.get(PriceParsingRule, rid)
        rule.sheets_config = fixed
        flag_modified(rule, "sheets_config")
        await s.commit()

    # 现在 aggregate 应只算 main(456000 而非 912000)
    async with async_session() as s:
        summaries = await aggregate_bidder_totals(s, pid, _cfg())
    assert summaries[0]["total_price"] == 456000.0
