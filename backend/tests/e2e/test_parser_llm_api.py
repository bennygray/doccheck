"""L2 - C5 LLM 分类 + 报价规则识别 + rule_coordinator 并发 (spec Req 2+3)"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest_asyncio
from sqlalchemy import delete, select

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_text import DocumentText
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project
from app.models.user import User
from app.services.auth.password import hash_password
from app.services.parser.llm.role_classifier import classify_bidder
from app.services.parser.pipeline import rule_coordinator
from app.services.parser.pipeline.rule_coordinator import acquire_or_wait_rule
from tests.fixtures.auth_fixtures import clean_users as _clean_users  # noqa
from tests.fixtures.doc_fixtures import make_price_xlsx
from tests.fixtures.llm_mock import (
    ScriptedLLMProvider,
    make_price_rule_response,
    make_role_classify_response,
)

os.environ.setdefault("INFRA_DISABLE_PIPELINE", "1")


async def _seed_project_bidder_docs(doc_specs: list[tuple[str, str]]):
    """seed (user, project, bidder, docs) 返回 (project_id, bidder_id, doc_ids)"""
    async with async_session() as s:
        user = User(
            username="lx",
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
        doc_ids: list[int] = []
        for i, (name, ext) in enumerate(doc_specs):
            doc = BidDocument(
                bidder_id=bidder.id,
                file_name=name,
                file_path=f"/tmp/p{i}",
                file_size=100,
                file_type=ext,
                md5=(f"{i:02d}" + "b" * 30)[:32],
                source_archive="a.zip",
                parse_status="identified",
            )
            s.add(doc)
            await s.flush()
            s.add(
                DocumentText(
                    bid_document_id=doc.id,
                    paragraph_index=0,
                    text="first paragraph text",
                    location="body",
                )
            )
            doc_ids.append(doc.id)
        await s.commit()
        return project.id, bidder.id, doc_ids


async def test_classify_bidder_success(clean_users):
    pid, bid, doc_ids = await _seed_project_bidder_docs(
        [("技术方案.docx", ".docx"), ("投标报价.xlsx", ".xlsx")]
    )
    llm = ScriptedLLMProvider(
        [
            make_role_classify_response(
                [(doc_ids[0], "technical"), (doc_ids[1], "pricing")],
                identity_info={
                    "company_full_name": "A公司",
                    "project_manager": "张三",
                },
            )
        ]
    )
    async with async_session() as s:
        result = await classify_bidder(s, bid, llm)
    assert result.llm_used is True

    async with async_session() as s:
        bidder = await s.get(Bidder, bid)
        assert bidder.identity_info == {
            "company_full_name": "A公司",
            "project_manager": "张三",
        }
        docs = (
            await s.execute(select(BidDocument).where(BidDocument.bidder_id == bid))
        ).scalars().all()
        roles = {d.file_name: d.file_role for d in docs}
        assert roles["技术方案.docx"] == "technical"
        assert roles["投标报价.xlsx"] == "pricing"


async def test_classify_bidder_llm_timeout_fallback_keywords(clean_users):
    pid, bid, _ = await _seed_project_bidder_docs(
        [("投标报价.xlsx", ".xlsx"), ("XYZ.docx", ".docx")]
    )
    from app.services.llm.base import LLMError

    llm = ScriptedLLMProvider([LLMError(kind="timeout", message="boom")])
    async with async_session() as s:
        result = await classify_bidder(s, bid, llm)
    assert result.llm_used is False

    async with async_session() as s:
        docs = (
            await s.execute(select(BidDocument).where(BidDocument.bidder_id == bid))
        ).scalars().all()
        by_name = {d.file_name: d for d in docs}
        assert by_name["投标报价.xlsx"].file_role == "pricing"
        assert by_name["投标报价.xlsx"].role_confidence == "low"
        assert by_name["XYZ.docx"].file_role == "other"
        # 身份信息不兜底
        bidder = await s.get(Bidder, bid)
        assert bidder.identity_info is None


async def test_classify_bidder_partial_missing_docs_fallback(clean_users):
    """LLM 只给了部分 doc,剩下的走规则兜底。"""
    pid, bid, doc_ids = await _seed_project_bidder_docs(
        [("技术方案.docx", ".docx"), ("未列.docx", ".docx")]
    )
    # LLM 只给 doc_ids[0]
    llm = ScriptedLLMProvider(
        [make_role_classify_response([(doc_ids[0], "technical")])]
    )
    async with async_session() as s:
        await classify_bidder(s, bid, llm)

    async with async_session() as s:
        docs = (
            await s.execute(select(BidDocument).where(BidDocument.bidder_id == bid))
        ).scalars().all()
        by_name = {d.file_name: d for d in docs}
        assert by_name["技术方案.docx"].file_role == "technical"
        assert by_name["技术方案.docx"].role_confidence == "high"
        # 漏的那条走规则兜底(无关键字 → other)
        assert by_name["未列.docx"].file_role == "other"
        assert by_name["未列.docx"].role_confidence == "low"


async def test_rule_coordinator_first_caller(clean_users, tmp_path: Path):
    rule_coordinator.reset_for_tests()
    pid, _bid, _ = await _seed_project_bidder_docs([("a.xlsx", ".xlsx")])
    xlsx = make_price_xlsx(tmp_path / "p.xlsx")
    llm = ScriptedLLMProvider([make_price_rule_response()])
    rule = await acquire_or_wait_rule(pid, xlsx, llm)
    assert rule is not None
    assert rule.status == "confirmed"
    assert rule.confirmed is True


async def test_rule_coordinator_llm_failure(clean_users, tmp_path: Path):
    from app.services.llm.base import LLMError

    rule_coordinator.reset_for_tests()
    pid, _bid, _ = await _seed_project_bidder_docs([("a.xlsx", ".xlsx")])
    xlsx = make_price_xlsx(tmp_path / "p.xlsx")
    llm = ScriptedLLMProvider([LLMError(kind="timeout", message="x")])
    rule = await acquire_or_wait_rule(pid, xlsx, llm)
    assert rule is None

    async with async_session() as s:
        row = (
            await s.execute(
                select(PriceParsingRule).where(PriceParsingRule.project_id == pid)
            )
        ).scalar_one()
        assert row.status == "failed"


async def test_rule_coordinator_concurrency_single_llm_call(
    clean_users, tmp_path: Path
):
    """并发 3 个 bidder 同时请求规则 → 只有 1 个 LLM 调用发生。"""
    rule_coordinator.reset_for_tests()
    pid, _bid, _ = await _seed_project_bidder_docs([("a.xlsx", ".xlsx")])
    xlsx = make_price_xlsx(tmp_path / "p.xlsx")

    # 三个协程共享同一个 LLM provider(计数 calls)
    from dataclasses import dataclass
    from app.services.llm.base import LLMResult, Message

    @dataclass
    class CountingLLM:
        name: str = "counting"
        calls: int = 0

        async def complete(self, messages, **kw):
            self.calls += 1
            await asyncio.sleep(0.05)  # 让其他协程有机会进入等待
            return LLMResult(text=make_price_rule_response())

    llm = CountingLLM()
    results = await asyncio.gather(
        acquire_or_wait_rule(pid, xlsx, llm),
        acquire_or_wait_rule(pid, xlsx, llm),
        acquire_or_wait_rule(pid, xlsx, llm),
    )
    assert all(r is not None for r in results)
    assert all(r.id == results[0].id for r in results)
    assert llm.calls == 1, f"expected LLM called once, got {llm.calls}"
