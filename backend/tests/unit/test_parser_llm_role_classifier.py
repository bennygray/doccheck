"""L1 - parser/llm/role_classifier 单元测试 (C5 §9.5)

覆盖:LLM 成功 / LLM 超时走规则兜底 / LLM 非法 JSON 走兜底 / 低置信度标 low。
用 llm_mock fixture + SQLite in-memory / PostgreSQL test DB。
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_text import DocumentText
from app.models.project import Project
from app.models.user import User
from app.services.llm.base import LLMError, LLMResult, Message
from app.services.parser.llm.role_classifier import classify_bidder


@dataclass
class FakeLLM:
    name: str = "fake"
    response_text: str = ""
    error: LLMError | None = None
    calls: int = 0

    async def complete(self, messages: list[Message], **kw) -> LLMResult:
        self.calls += 1
        if self.error is not None:
            return LLMResult(text="", error=self.error)
        return LLMResult(text=self.response_text)


async def _seed_bidder_with_docs(
    session: AsyncSession, docs: list[dict]
) -> int:
    # seed user/project/bidder/docs;返 bidder_id
    user = User(
        username=f"rc_{id(session)}",
        password_hash="x",
        role="reviewer",
        login_fail_count=0,
    )
    session.add(user)
    await session.flush()

    project = Project(name="P", owner_id=user.id)
    session.add(project)
    await session.flush()

    bidder = Bidder(name="B", project_id=project.id, parse_status="extracted")
    session.add(bidder)
    await session.flush()

    for i, spec in enumerate(docs):
        bd = BidDocument(
            bidder_id=bidder.id,
            file_name=spec["name"],
            file_path=f"/tmp/fake{i}",
            file_size=100,
            file_type=spec.get("type", ".docx"),
            md5=(f"{i:02d}" + "x" * 30)[:32],  # 唯一 md5 per bidder
            source_archive="a.zip",
            parse_status="identified",
        )
        session.add(bd)
        await session.flush()
        # 首段文本
        session.add(
            DocumentText(
                bid_document_id=bd.id,
                paragraph_index=0,
                text=spec.get("first_text", "hello"),
                location="body",
            )
        )
    await session.commit()
    return bidder.id


@pytest_asyncio.fixture
async def clean_parser_data():
    """每个测试前后清干净,不影响 C2/C3/C4 fixture。"""
    from sqlalchemy import delete

    async with async_session() as session:
        for M in (DocumentText, BidDocument, Bidder, Project, User):
            await session.execute(delete(M).where(M.id > 0))
        await session.commit()
    yield
    async with async_session() as session:
        for M in (DocumentText, BidDocument, Bidder, Project, User):
            await session.execute(delete(M).where(M.id > 0))
        await session.commit()


@pytest.mark.asyncio
async def test_llm_success_roles_applied(clean_parser_data) -> None:
    async with async_session() as session:
        bidder_id = await _seed_bidder_with_docs(
            session,
            [{"name": "技术方案.docx"}, {"name": "报价.xlsx", "type": ".xlsx"}],
        )
        docs_ids = [d.id for d in (await session.execute(
            __import__("sqlalchemy").select(BidDocument)
            .where(BidDocument.bidder_id == bidder_id)
        )).scalars().all()]
        import json
        llm = FakeLLM(
            response_text=json.dumps(
                {
                    "roles": [
                        {"document_id": docs_ids[0], "role": "technical", "confidence": "high"},
                        {"document_id": docs_ids[1], "role": "pricing", "confidence": "high"},
                    ],
                    "identity_info": {"company_full_name": "某某公司"},
                }
            )
        )
        result = await classify_bidder(session, bidder_id, llm)

    assert result.llm_used is True
    assert result.documents_updated == 2

    # 验证 DB 更新
    from sqlalchemy import select
    async with async_session() as session:
        docs = (
            await session.execute(
                select(BidDocument).where(BidDocument.bidder_id == bidder_id)
            )
        ).scalars().all()
        by_name = {d.file_name: d for d in docs}
        assert by_name["技术方案.docx"].file_role == "technical"
        assert by_name["技术方案.docx"].role_confidence == "high"
        assert by_name["报价.xlsx"].file_role == "pricing"
        bidder = await session.get(Bidder, bidder_id)
        assert bidder.identity_info == {"company_full_name": "某某公司"}


@pytest.mark.asyncio
async def test_llm_timeout_fallback_to_keywords(clean_parser_data) -> None:
    async with async_session() as session:
        bidder_id = await _seed_bidder_with_docs(
            session,
            [{"name": "投标报价清单.xlsx", "type": ".xlsx"}],
        )
        llm = FakeLLM(error=LLMError(kind="timeout", message="boom"))
        result = await classify_bidder(session, bidder_id, llm)

    assert result.llm_used is False
    assert result.documents_updated == 1

    from sqlalchemy import select
    async with async_session() as session:
        doc = (
            await session.execute(select(BidDocument).where(BidDocument.bidder_id == bidder_id))
        ).scalar_one()
        assert doc.file_role == "pricing"  # keyword 命中"报价"
        assert doc.role_confidence == "low"
        bidder = await session.get(Bidder, bidder_id)
        assert bidder.identity_info is None  # 身份信息不走规则兜底


@pytest.mark.asyncio
async def test_llm_bad_json_fallback_to_keywords(clean_parser_data) -> None:
    async with async_session() as session:
        bidder_id = await _seed_bidder_with_docs(
            session, [{"name": "XYZ.docx"}]
        )
        llm = FakeLLM(response_text="{malformed")
        result = await classify_bidder(session, bidder_id, llm)

    assert result.llm_used is False
    from sqlalchemy import select
    async with async_session() as session:
        doc = (
            await session.execute(
                select(BidDocument).where(BidDocument.bidder_id == bidder_id)
            )
        ).scalar_one()
        assert doc.file_role == "other"  # 关键词未命中
        assert doc.role_confidence == "low"


@pytest.mark.asyncio
async def test_low_confidence_marked_low(clean_parser_data) -> None:
    async with async_session() as session:
        bidder_id = await _seed_bidder_with_docs(
            session, [{"name": "模糊文件.docx"}]
        )
        doc_id = (await session.execute(
            __import__("sqlalchemy").select(BidDocument).where(
                BidDocument.bidder_id == bidder_id
            )
        )).scalar_one().id

    import json
    llm = FakeLLM(
        response_text=json.dumps(
            {
                "roles": [
                    {
                        "document_id": doc_id,
                        "role": "technical",
                        "confidence": "low",
                    }
                ],
                "identity_info": {},
            }
        )
    )
    async with async_session() as session:
        await classify_bidder(session, bidder_id, llm)

    from sqlalchemy import select
    async with async_session() as session:
        doc = (
            await session.execute(select(BidDocument).where(BidDocument.id == doc_id))
        ).scalar_one()
        assert doc.file_role == "technical"
        assert doc.role_confidence == "low"
