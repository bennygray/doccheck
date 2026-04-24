"""L2 - run_pipeline → classify_bidder → 关键词兜底链路
(fix-mac-packed-zip-parsing 4.2)。

与 tests/unit/test_role_classifier_content_fallback.py 的区别:
- L1 直接单测 classify_bidder
- L2 走 run_pipeline 整条链路(phase1 被 seed 绕过,phase2 LLM mock 成 timeout)
确保正文关键词兜底在流水线集成点生效。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

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
from app.services.parser.pipeline.run_pipeline import run_pipeline


@dataclass
class TimeoutLLM:
    """每次调用都返 timeout 错,触发 classify_bidder 兜底路径。"""

    name: str = "timeout"
    calls: int = 0

    async def complete(self, messages: list[Message], **kw) -> LLMResult:
        self.calls += 1
        return LLMResult(text="", error=LLMError(kind="timeout", message="t/o"))


@pytest_asyncio.fixture
async def clean_kw_fb_data():
    prefix = "rc_kwfb_"

    async def _purge():
        async with async_session() as s:
            user_ids = (
                await s.execute(
                    select(User.id).where(User.username.like(f"{prefix}%"))
                )
            ).scalars().all()
            if not user_ids:
                return
            project_ids = (
                await s.execute(
                    select(Project.id).where(Project.owner_id.in_(user_ids))
                )
            ).scalars().all()
            bidder_ids = (
                (
                    await s.execute(
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
                    await s.execute(
                        select(BidDocument.id).where(
                            BidDocument.bidder_id.in_(bidder_ids)
                        )
                    )
                ).scalars().all()
                if bidder_ids
                else []
            )
            if doc_ids:
                await s.execute(
                    delete(DocumentText).where(
                        DocumentText.bid_document_id.in_(doc_ids)
                    )
                )
                await s.execute(
                    delete(DocumentMetadata).where(
                        DocumentMetadata.bid_document_id.in_(doc_ids)
                    )
                )
                await s.execute(
                    delete(DocumentImage).where(
                        DocumentImage.bid_document_id.in_(doc_ids)
                    )
                )
                await s.execute(
                    delete(DocumentSheet).where(
                        DocumentSheet.bid_document_id.in_(doc_ids)
                    )
                )
                await s.execute(
                    delete(BidDocument).where(BidDocument.id.in_(doc_ids))
                )
            if bidder_ids:
                await s.execute(
                    delete(Bidder).where(Bidder.id.in_(bidder_ids))
                )
            if project_ids:
                await s.execute(
                    delete(Project).where(Project.id.in_(project_ids))
                )
            await s.execute(delete(User).where(User.id.in_(user_ids)))
            await s.commit()

    await _purge()
    yield
    await _purge()


@pytest.fixture(autouse=True)
def _skip_phase1_extract(monkeypatch):
    """run_pipeline 的 phase1 会调 extract_content(从磁盘读 docx),测试里
    没有真实 docx 文件,直接把 phase1 patch 成 no-op;phase3(报价)不影响。"""
    from app.services.parser.pipeline import run_pipeline as rp

    async def _noop(bidder_id: int) -> None:
        return None

    monkeypatch.setattr(rp, "_phase_extract_content", _noop)


@pytest.fixture(autouse=True)
def _disable_auto_extract():
    prev = os.environ.get("INFRA_DISABLE_EXTRACT")
    os.environ["INFRA_DISABLE_EXTRACT"] = "1"
    yield
    if prev is None:
        os.environ.pop("INFRA_DISABLE_EXTRACT", None)
    else:
        os.environ["INFRA_DISABLE_EXTRACT"] = prev


async def _seed(
    *, tag: str, file_name: str, first_text: str, parse_status: str = "identified"
) -> int:
    async with async_session() as s:
        user = User(
            username=f"rc_kwfb_{tag}",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        s.add(user)
        await s.flush()
        project = Project(name=f"P_{tag}", owner_id=user.id)
        s.add(project)
        await s.flush()
        bidder = Bidder(
            name=f"B_{tag}", project_id=project.id, parse_status="extracted"
        )
        s.add(bidder)
        await s.flush()
        bd = BidDocument(
            bidder_id=bidder.id,
            file_name=file_name,
            file_path=f"/tmp/kwfb_{tag}",
            file_size=100,
            file_type=".docx",
            md5=(f"{tag[:4]}" + "z" * 30)[:32],
            source_archive="a.zip",
            parse_status=parse_status,
        )
        s.add(bd)
        await s.flush()
        s.add(
            DocumentText(
                bid_document_id=bd.id,
                paragraph_index=0,
                text=first_text,
                location="body",
            )
        )
        await s.commit()
        return bidder.id


@pytest.mark.asyncio
async def test_run_pipeline_llm_timeout_content_keyword_yields_technical(
    clean_kw_fb_data,
) -> None:
    """文件名乱码 + 正文含 "技术方案" + LLM 超时 → file_role=technical low。"""
    # UTF-8 字节被按 cp437 呈现的典型乱码形态
    mojibake_name = "\u03a3\u255b\u00a2\u03c3\u2557\u00f6\u03c3\u00f2\u00e5.docx"
    bidder_id = await _seed(
        tag="tech",
        file_name=mojibake_name,
        first_text="本公司技术方案概述如下,拟采用...",
    )

    llm = TimeoutLLM()
    await run_pipeline(bidder_id, llm=llm)
    assert llm.calls >= 1

    async with async_session() as s:
        docs = (
            await s.execute(
                select(BidDocument).where(BidDocument.bidder_id == bidder_id)
            )
        ).scalars().all()
        assert len(docs) == 1
        assert docs[0].file_role == "technical"
        assert docs[0].role_confidence == "low"


@pytest.mark.asyncio
async def test_run_pipeline_llm_timeout_no_content_uses_filename(
    clean_kw_fb_data,
) -> None:
    """文件名正常("投标报价.xlsx")+ 正文无关键词 + LLM 超时 → 走文件名 pricing。"""
    bidder_id = await _seed(
        tag="fn",
        file_name="投标报价.xlsx",
        first_text="lorem ipsum",
    )
    llm = TimeoutLLM()
    await run_pipeline(bidder_id, llm=llm)

    async with async_session() as s:
        doc = (
            await s.execute(
                select(BidDocument).where(BidDocument.bidder_id == bidder_id)
            )
        ).scalar_one()
        assert doc.file_role == "pricing"
        assert doc.role_confidence == "low"
