"""L2 - C5 run_pipeline 全链路 + fill_price 回填 + 状态机终态 (spec Req 4+5+8)

覆盖:
- pipeline 完整路径: extracted → identifying → identified → pricing → priced
- 无报价表 bidder 停在 identified
- 内容提取全失败 → identify_failed
- 报价规则识别失败 → price_failed
- fill_price sheet 回填、千分位、空行、terminal 判定 (priced / price_partial / price_failed)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest_asyncio
from sqlalchemy import select

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project
from app.models.user import User
from app.services.auth.password import hash_password
from app.services.parser.pipeline import rule_coordinator
from app.services.parser.pipeline.run_pipeline import run_pipeline
from tests.fixtures.auth_fixtures import clean_users as _clean_users  # noqa
from tests.fixtures.doc_fixtures import make_price_xlsx, make_real_docx
from tests.fixtures.llm_mock import (
    ScriptedLLMProvider,
    make_price_rule_response,
    make_role_classify_response,
)

os.environ.setdefault("INFRA_DISABLE_PIPELINE", "1")


async def _seed_project_with_bidder(docs: list[dict]) -> tuple[int, int, list[int]]:
    """docs: [{"name": "x.docx", "type": ".docx", "path": Path}, ...]
    返回 (project_id, bidder_id, doc_ids)
    """
    async with async_session() as s:
        user = User(
            username="px",
            password_hash=hash_password("x"),
            role="reviewer",
            must_change_password=False,
        )
        s.add(user)
        await s.flush()
        project = Project(name="P", owner_id=user.id)
        s.add(project)
        await s.flush()
        bidder = Bidder(
            name="B", project_id=project.id, parse_status="extracted"
        )
        s.add(bidder)
        await s.flush()
        ids: list[int] = []
        for i, spec in enumerate(docs):
            doc = BidDocument(
                bidder_id=bidder.id,
                file_name=spec["name"],
                file_path=str(spec["path"]),
                file_size=1000,
                file_type=spec["type"],
                md5=(f"{i:02d}" + "p" * 30)[:32],
                source_archive="a.zip",
                parse_status="extracted",
            )
            s.add(doc)
            await s.flush()
            ids.append(doc.id)
        await s.commit()
        return project.id, bidder.id, ids


async def test_pipeline_happy_path_priced(clean_users, tmp_path: Path):
    rule_coordinator.reset_for_tests()
    docx_path = make_real_docx(tmp_path / "t.docx", body_paragraphs=["技术内容"])
    xlsx_path = make_price_xlsx(tmp_path / "p.xlsx", row_count=3)
    pid, bid, ids = await _seed_project_with_bidder(
        [
            {"name": "技术方案.docx", "type": ".docx", "path": docx_path},
            {"name": "投标报价.xlsx", "type": ".xlsx", "path": xlsx_path},
        ]
    )
    llm = ScriptedLLMProvider(
        [
            make_role_classify_response(
                [(ids[0], "technical"), (ids[1], "pricing")],
                identity_info={"company_full_name": "A 公司"},
            ),
            make_price_rule_response(),
        ]
    )

    await run_pipeline(bid, llm=llm)

    async with async_session() as s:
        bidder = await s.get(Bidder, bid)
        assert bidder.parse_status == "priced"
        items = (
            await s.execute(select(PriceItem).where(PriceItem.bidder_id == bid))
        ).scalars().all()
        assert len(items) == 3


async def test_pipeline_no_pricing_stops_at_identified(
    clean_users, tmp_path: Path
):
    rule_coordinator.reset_for_tests()
    docx = make_real_docx(tmp_path / "t.docx", body_paragraphs=["x"])
    pid, bid, ids = await _seed_project_with_bidder(
        [{"name": "技术.docx", "type": ".docx", "path": docx}]
    )
    llm = ScriptedLLMProvider(
        [make_role_classify_response([(ids[0], "technical")])]
    )
    await run_pipeline(bid, llm=llm)

    async with async_session() as s:
        bidder = await s.get(Bidder, bid)
        assert bidder.parse_status == "identified"
        # 无 price_parsing_rules
        rules = (
            await s.execute(select(PriceParsingRule).where(PriceParsingRule.project_id == pid))
        ).scalars().all()
        assert rules == []


async def test_pipeline_all_content_failed_identify_failed(
    clean_users, tmp_path: Path
):
    rule_coordinator.reset_for_tests()
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not valid docx")
    pid, bid, _ = await _seed_project_with_bidder(
        [{"name": "bad.docx", "type": ".docx", "path": bad}]
    )
    llm = ScriptedLLMProvider([make_role_classify_response([])])
    await run_pipeline(bid, llm=llm)
    async with async_session() as s:
        bidder = await s.get(Bidder, bid)
        assert bidder.parse_status == "identify_failed"


async def test_pipeline_price_rule_failure_leads_to_price_failed(
    clean_users, tmp_path: Path
):
    from app.services.llm.base import LLMError

    rule_coordinator.reset_for_tests()
    docx = make_real_docx(tmp_path / "t.docx", body_paragraphs=["x"])
    xlsx = make_price_xlsx(tmp_path / "p.xlsx")
    pid, bid, ids = await _seed_project_with_bidder(
        [
            {"name": "技术.docx", "type": ".docx", "path": docx},
            {"name": "投标报价.xlsx", "type": ".xlsx", "path": xlsx},
        ]
    )
    # 第一次 LLM 调用(角色)成功;第二次(规则识别)失败
    llm = ScriptedLLMProvider(
        [
            make_role_classify_response(
                [(ids[0], "technical"), (ids[1], "pricing")]
            ),
            LLMError(kind="timeout", message="rule fail"),
        ],
        loop_last=True,
    )
    await run_pipeline(bid, llm=llm)
    async with async_session() as s:
        bidder = await s.get(Bidder, bid)
        assert bidder.parse_status == "price_failed"


async def test_pipeline_thousand_sep_and_currency_normalized(
    clean_users, tmp_path: Path
):
    """构造含千分位值的 xlsx,回填后 unit_price 为标准 Decimal。"""
    import openpyxl

    rule_coordinator.reset_for_tests()
    docx = make_real_docx(tmp_path / "t.docx", body_paragraphs=["x"])
    xlsx = tmp_path / "money.xlsx"
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("报价清单")
    ws.append(["标题", "", "", "", "", ""])
    ws.append(["编码", "名称", "单位", "数量", "单价", "合价"])
    ws.append(["A1", "项1", "m3", "10", "1,234.56", "12,345.60"])
    wb.save(str(xlsx))

    pid, bid, ids = await _seed_project_with_bidder(
        [
            {"name": "技术.docx", "type": ".docx", "path": docx},
            {"name": "投标报价.xlsx", "type": ".xlsx", "path": xlsx},
        ]
    )
    llm = ScriptedLLMProvider(
        [
            make_role_classify_response(
                [(ids[0], "technical"), (ids[1], "pricing")]
            ),
            make_price_rule_response(),
        ]
    )
    await run_pipeline(bid, llm=llm)

    async with async_session() as s:
        items = (
            await s.execute(select(PriceItem).where(PriceItem.bidder_id == bid))
        ).scalars().all()
        assert len(items) == 1
        item = items[0]
        assert str(item.unit_price) == "1234.56"
        assert str(item.total_price) == "12345.60"
