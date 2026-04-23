"""L1 - role_classifier 两级兜底 (fix-mac-packed-zip-parsing 3.4)。

验证 LLM 失败后的兜底链路:
1. 先走正文关键词匹配(parse_status=identified + document_texts 首段)
2. 未命中再走文件名关键词匹配
3. 仍未命中 → 'other'
4. 均标 role_confidence='low'
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_image import DocumentImage
from app.models.document_metadata import DocumentMetadata
from app.models.document_sheet import DocumentSheet
from app.models.document_text import DocumentText
from app.models.project import Project
from app.models.user import User
from app.services.llm.base import LLMError, LLMResult, Message
from app.services.parser.llm.role_classifier import classify_bidder


@dataclass
class FakeLLM:
    """触发规则兜底路径的 mock LLM。"""

    name: str = "fake"
    error: LLMError | None = None
    calls: int = 0

    async def complete(self, messages: list[Message], **kw) -> LLMResult:
        self.calls += 1
        err = self.error or LLMError(kind="timeout", message="boom")
        return LLMResult(text="", error=err)


async def _seed(
    session: AsyncSession, docs: list[dict], tag: str
) -> tuple[int, list[int]]:
    """批量种子;docs 每项含 name / first_text / parse_status。返 (bidder_id, [doc_ids])。"""
    user = User(
        username=f"rc_cfb_{tag}_{id(session)}",
        password_hash="x",
        role="reviewer",
        login_fail_count=0,
    )
    session.add(user)
    await session.flush()
    project = Project(name=f"P_{tag}", owner_id=user.id)
    session.add(project)
    await session.flush()
    bidder = Bidder(
        name=f"B_{tag}", project_id=project.id, parse_status="extracted"
    )
    session.add(bidder)
    await session.flush()
    doc_ids: list[int] = []
    for i, spec in enumerate(docs):
        bd = BidDocument(
            bidder_id=bidder.id,
            file_name=spec["name"],
            file_path=f"/tmp/fake_{tag}_{i}",
            file_size=100,
            file_type=spec.get("type", ".docx"),
            md5=(f"{tag[:4]}{i:02d}" + "x" * 30)[:32],
            source_archive="a.zip",
            parse_status=spec.get("parse_status", "identified"),
        )
        session.add(bd)
        await session.flush()
        doc_ids.append(bd.id)
        first_text = spec.get("first_text")
        if first_text:
            session.add(
                DocumentText(
                    bid_document_id=bd.id,
                    paragraph_index=0,
                    text=first_text,
                    location="body",
                )
            )
    await session.commit()
    return bidder.id, doc_ids


@pytest_asyncio.fixture
async def clean_role_fallback_data():
    """只清理本测试文件 seed 的行(按 User.username 前缀过滤),
    不动共享 DB 里其他测试或手工调试产生的数据。"""

    prefix = "rc_cfb_"

    async def _purge():
        async with async_session() as session:
            # 先查出本测试文件造的 user_id 集合
            user_ids = (
                await session.execute(
                    select(User.id).where(User.username.like(f"{prefix}%"))
                )
            ).scalars().all()
            if not user_ids:
                return
            project_ids = (
                await session.execute(
                    select(Project.id).where(Project.owner_id.in_(user_ids))
                )
            ).scalars().all()
            bidder_ids = (
                (
                    await session.execute(
                        select(Bidder.id).where(
                            Bidder.project_id.in_(project_ids)
                        )
                    )
                ).scalars().all()
                if project_ids
                else []
            )
            doc_ids = (
                (
                    await session.execute(
                        select(BidDocument.id).where(
                            BidDocument.bidder_id.in_(bidder_ids)
                        )
                    )
                ).scalars().all()
                if bidder_ids
                else []
            )
            if doc_ids:
                await session.execute(
                    delete(DocumentText).where(
                        DocumentText.bid_document_id.in_(doc_ids)
                    )
                )
                await session.execute(
                    delete(DocumentMetadata).where(
                        DocumentMetadata.bid_document_id.in_(doc_ids)
                    )
                )
                await session.execute(
                    delete(DocumentImage).where(
                        DocumentImage.bid_document_id.in_(doc_ids)
                    )
                )
                await session.execute(
                    delete(DocumentSheet).where(
                        DocumentSheet.bid_document_id.in_(doc_ids)
                    )
                )
                await session.execute(
                    delete(BidDocument).where(BidDocument.id.in_(doc_ids))
                )
            if bidder_ids:
                await session.execute(
                    delete(Bidder).where(Bidder.id.in_(bidder_ids))
                )
            if project_ids:
                await session.execute(
                    delete(Project).where(Project.id.in_(project_ids))
                )
            await session.execute(
                delete(User).where(User.id.in_(user_ids))
            )
            await session.commit()

    await _purge()
    yield
    await _purge()


async def _fetch_doc(bidder_id: int, doc_id: int) -> BidDocument:
    async with async_session() as session:
        return (
            await session.execute(
                select(BidDocument).where(BidDocument.id == doc_id)
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_mojibake_filename_content_has_pricing_keyword(
    clean_role_fallback_data,
) -> None:
    """乱码文件名 + 正文含"投标报价一览表" → role=pricing(走正文兜底)。"""
    async with async_session() as session:
        bidder_id, doc_ids = await _seed(
            session,
            [
                {
                    "name": "\u03a3\u255b\u00a2\u03c3\u2557\u00f6\u03c3\u00f2\u00e5.docx",
                    "first_text": "本公司针对本次招标项目提交投标报价一览表如下",
                },
            ],
            tag="pricing",
        )
        llm = FakeLLM()
        result = await classify_bidder(session, bidder_id, llm)
    assert result.llm_used is False

    doc = await _fetch_doc(bidder_id, doc_ids[0])
    assert doc.file_role == "pricing"
    assert doc.role_confidence == "low"


@pytest.mark.asyncio
async def test_mojibake_filename_content_has_technical_keyword(
    clean_role_fallback_data,
) -> None:
    async with async_session() as session:
        bidder_id, doc_ids = await _seed(
            session,
            [
                {
                    "name": "xxxxxx.docx",
                    "first_text": "技术方案概述,本公司拟采用...",
                },
            ],
            tag="tech",
        )
        llm = FakeLLM()
        await classify_bidder(session, bidder_id, llm)

    doc = await _fetch_doc(0, doc_ids[0])
    assert doc.file_role == "technical"
    assert doc.role_confidence == "low"


@pytest.mark.asyncio
async def test_mojibake_filename_and_content_both_miss(
    clean_role_fallback_data,
) -> None:
    async with async_session() as session:
        bidder_id, doc_ids = await _seed(
            session,
            [
                {
                    "name": "xxxxxx.docx",
                    "first_text": "完全无关的随机文本 lorem ipsum",
                },
            ],
            tag="miss",
        )
        llm = FakeLLM()
        await classify_bidder(session, bidder_id, llm)

    doc = await _fetch_doc(0, doc_ids[0])
    assert doc.file_role == "other"
    assert doc.role_confidence == "low"


@pytest.mark.asyncio
async def test_good_filename_empty_content_uses_filename(
    clean_role_fallback_data,
) -> None:
    """文件名正常("投标报价.xlsx")+ 正文空 → 走文件名路径,role=pricing。"""
    async with async_session() as session:
        bidder_id, doc_ids = await _seed(
            session,
            [
                {
                    "name": "投标报价.xlsx",
                    "type": ".xlsx",
                    # 不插 document_text
                },
            ],
            tag="fname",
        )
        llm = FakeLLM()
        await classify_bidder(session, bidder_id, llm)

    doc = await _fetch_doc(0, doc_ids[0])
    assert doc.file_role == "pricing"
    assert doc.role_confidence == "low"


@pytest.mark.asyncio
async def test_not_identified_skips_content_goes_to_filename(
    clean_role_fallback_data,
) -> None:
    """parse_status != 'identified' → 跳过正文兜底,直接走文件名关键词。"""
    async with async_session() as session:
        bidder_id, doc_ids = await _seed(
            session,
            [
                {
                    "name": "投标报价清单.xlsx",
                    "type": ".xlsx",
                    "parse_status": "identify_failed",
                    # 插了正文,但应被跳过
                    "first_text": "技术方案概述",
                },
            ],
            tag="notid",
        )
        llm = FakeLLM()
        await classify_bidder(session, bidder_id, llm)

    doc = await _fetch_doc(0, doc_ids[0])
    # 走文件名兜底(含 "报价")→ pricing,而非正文的 technical
    assert doc.file_role == "pricing"
    assert doc.role_confidence == "low"


@pytest.mark.asyncio
async def test_content_keyword_beats_filename_keyword_on_conflict(
    clean_role_fallback_data,
) -> None:
    """文件名和正文都有关键词时,正文优先。
    (文件名命中 'authorization' 但正文命中 'pricing' → pricing)"""
    async with async_session() as session:
        bidder_id, doc_ids = await _seed(
            session,
            [
                {
                    "name": "授权委托书.docx",
                    "first_text": "本公司提交投标报价如下",
                },
            ],
            tag="conflict",
        )
        llm = FakeLLM()
        await classify_bidder(session, bidder_id, llm)

    doc = await _fetch_doc(0, doc_ids[0])
    assert doc.file_role == "pricing"
    assert doc.role_confidence == "low"
