"""L1 - aggregate_bidder_totals 扩 excluded_price_item_ids kwarg 回归保护
(detect-tender-baseline §6.1-i / D15)

D15 决策:扩 keyword-only `excluded_price_item_ids: set[int] | None = None` 参数。
- 默认 None / 空 set → SQL WHERE 子句不变 → 3 共用 agent
  (price_anomaly / price_overshoot / price_total_match) **行为完全不变**
- 非空 set → SQL WHERE 加 `AND PriceItem.id NOT IN :excluded` → SUM 排除 baseline 命中行

复用 [test_price_anomaly_extractor.py] 已有的 `async_session` + `clean_tables` 模式。
"""

from __future__ import annotations

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
from app.models.user import User
from app.services.detect.agents.anomaly_impl.config import AnomalyConfig
from app.services.detect.agents.anomaly_impl.extractor import (
    aggregate_bidder_totals,
)

pytestmark = pytest.mark.asyncio


def _cfg(max_bidders: int = 50) -> AnomalyConfig:
    return AnomalyConfig(
        enabled=True,
        min_sample_size=3,
        deviation_threshold=0.30,
        direction="low",
        baseline_enabled=False,
        max_bidders=max_bidders,
        weight=1.0,
    )


@pytest_asyncio.fixture
async def clean_tables():
    async with async_session() as s:
        await s.execute(delete(PriceItem))
        await s.execute(delete(PriceParsingRule))
        await s.execute(delete(BidDocument))
        await s.execute(delete(Bidder))
        await s.execute(delete(Project))
        await s.execute(delete(User))
        await s.commit()
    yield
    async with async_session() as s:
        await s.execute(delete(PriceItem))
        await s.execute(delete(PriceParsingRule))
        await s.execute(delete(BidDocument))
        await s.execute(delete(Bidder))
        await s.execute(delete(Project))
        await s.execute(delete(User))
        await s.commit()


async def _seed_basic() -> tuple[int, list[int], list[int]]:
    """seed: 1 user / 1 project / 1 rule(sheet_role=main) / 3 bidders × 5 PriceItem。

    返 (project_id, bidder_ids, all_price_item_ids)。
    """
    async with async_session() as s:
        u = User(username="anom_excl_test", password_hash="x"*60, role="reviewer", is_active=True, must_change_password=False)
        s.add(u)
        await s.flush()
        p = Project(name="anom_excl_proj", owner_id=u.id, status="ready")
        s.add(p)
        await s.flush()
        rule = PriceParsingRule(
            project_id=p.id, sheet_name="清单表", header_row=1,
            column_mapping={
                "code_col": 0, "name_col": 1, "unit_col": 2,
                "qty_col": 3, "unit_price_col": 4, "total_price_col": 5,
            },
            sheets_config=[{
                "sheet_name": "清单表",
                "sheet_role": "main",
                "header_row": 1,
                "column_mapping": {
                    "code_col": 0, "name_col": 1, "unit_col": 2,
                    "qty_col": 3, "unit_price_col": 4, "total_price_col": 5,
                },
            }],
        )
        s.add(rule)
        await s.flush()
        bidder_ids: list[int] = []
        for letter in ["A", "B", "C"]:
            b = Bidder(name=f"vendor-{letter}_excl", project_id=p.id, parse_status="priced")
            s.add(b)
            await s.flush()
            bidder_ids.append(b.id)
            for i in range(5):
                pi = PriceItem(
                    bidder_id=b.id, price_parsing_rule_id=rule.id,
                    sheet_name="清单表", row_index=i + 1,
                    item_name=f"项目{i+1}",
                    unit_price=Decimal("100"), total_price=Decimal("500"),
                )
                s.add(pi)
        await s.commit()
        rows = (await s.execute(select(PriceItem.id).order_by(PriceItem.id))).all()
        pi_ids = [r[0] for r in rows]
        return p.id, bidder_ids, pi_ids


# ============================================================ 默认 None 行为不变(回归保护)


async def test_default_none_behavior_unchanged(clean_tables):
    """default `excluded_price_item_ids=None` → SQL 不加额外 WHERE → 3 共用 agent 行为不变。"""
    pid, bidders, _ = await _seed_basic()
    cfg = _cfg()

    async with async_session() as s:
        s1 = await aggregate_bidder_totals(s, pid, cfg)
        s2 = await aggregate_bidder_totals(s, pid, cfg, excluded_price_item_ids=None)
        s3 = await aggregate_bidder_totals(s, pid, cfg, excluded_price_item_ids=set())

    assert len(s1) == 3
    # 3 个调用结果完全一致 — 顺序、bidder_id、total_price 都同
    assert [(x["bidder_id"], x["total_price"]) for x in s1] == [(x["bidder_id"], x["total_price"]) for x in s2]
    assert [(x["bidder_id"], x["total_price"]) for x in s1] == [(x["bidder_id"], x["total_price"]) for x in s3]
    # 每家 5 行 × 500 = 2500
    for x in s1:
        assert x["total_price"] == 2500.0


# ============================================================ 非空 set 过滤生效


async def test_excluded_set_filters_price_items(clean_tables):
    """传非空 set → SUM 排除指定 PriceItem.id → bidder 的 total 下降。"""
    pid, bidders, pi_ids = await _seed_basic()
    cfg = _cfg()

    # 排除前 2 个 PriceItem(都是 vendor A 的;A: pi_ids[0..4],B: pi_ids[5..9],C: pi_ids[10..14])
    excluded = {pi_ids[0], pi_ids[1]}
    async with async_session() as s:
        result = await aggregate_bidder_totals(s, pid, cfg, excluded_price_item_ids=excluded)

    by_bidder = {x["bidder_id"]: x["total_price"] for x in result}
    # vendor-A 少 2 行 × 500 = 1000 → total = 1500
    assert by_bidder[bidders[0]] == 1500.0
    # B / C 不变
    assert by_bidder[bidders[1]] == 2500.0
    assert by_bidder[bidders[2]] == 2500.0


async def test_excluded_set_filters_all_items_for_one_bidder(clean_tables):
    """排除某 bidder 的全部 PriceItem → 该 bidder 完全从结果中消失
    (SUM 后 total=NULL → 在 extractor 内被过滤,见原 fix-multi-sheet 约定)。"""
    pid, bidders, pi_ids = await _seed_basic()
    cfg = _cfg()

    # 排除 vendor-A 的全部 5 行
    excluded = set(pi_ids[:5])
    async with async_session() as s:
        result = await aggregate_bidder_totals(s, pid, cfg, excluded_price_item_ids=excluded)

    by_bidder = {x["bidder_id"]: x["total_price"] for x in result}
    assert bidders[0] not in by_bidder, "全行被剔除的 bidder MUST 不在结果"
    assert by_bidder[bidders[1]] == 2500.0
    assert by_bidder[bidders[2]] == 2500.0


async def test_excluded_set_with_unrelated_ids_no_effect(clean_tables):
    """传与项目无关的 PriceItem.id → 对本项目 SUM 无影响
    (WHERE Bidder.project_id 已先过滤,IN clause 只是叠加条件)。"""
    pid, bidders, _ = await _seed_basic()
    cfg = _cfg()

    async with async_session() as s:
        result = await aggregate_bidder_totals(s, pid, cfg, excluded_price_item_ids={99999, 99998})

    by_bidder = {x["bidder_id"]: x["total_price"] for x in result}
    assert by_bidder[bidders[0]] == 2500.0
    assert by_bidder[bidders[1]] == 2500.0
    assert by_bidder[bidders[2]] == 2500.0


async def test_excluded_set_keyword_only(clean_tables):
    """`excluded_price_item_ids` 必须是 keyword-only(positional 调用 MUST raise)。"""
    pid, _, _ = await _seed_basic()
    cfg = _cfg()

    async with async_session() as s:
        with pytest.raises(TypeError):
            # 4 个 positional args 应该报错(签名是 3 positional + keyword-only)
            await aggregate_bidder_totals(s, pid, cfg, set())  # type: ignore[misc]
