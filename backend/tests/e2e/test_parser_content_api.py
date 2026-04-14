"""L2 - C5 parser/content extract_content 覆盖 (spec "文档内容提取")

通过直接调用 extract_content(不走 pipeline 协程),单测真实 docx/xlsx 文件 →
document_texts / document_metadata / document_images 落库。
INFRA_DISABLE_PIPELINE=1 已在 conftest 里保证(避免协程并发干扰断言)。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_image import DocumentImage
from app.models.document_metadata import DocumentMetadata
from app.models.document_text import DocumentText
from app.models.project import Project
from app.models.user import User
from app.services.parser.content import extract_content
from tests.fixtures.auth_fixtures import clean_users as _clean_users  # noqa
from tests.fixtures.doc_fixtures import make_real_docx, make_real_xlsx

os.environ.setdefault("INFRA_DISABLE_PIPELINE", "1")


@pytest_asyncio.fixture
async def seed_bidder_with_file(clean_users, tmp_path: Path):
    """工厂:seed 一个 bidder + 一个 bid_document 指向真实文件。返回 doc_id。"""

    async def _make(file_path: Path, file_type: str) -> int:
        from app.services.auth.password import hash_password

        async with async_session() as s:
            user = User(
                username="cx",
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
            doc = BidDocument(
                bidder_id=bidder.id,
                file_name=file_path.name,
                file_path=str(file_path),
                file_size=file_path.stat().st_size,
                file_type=file_type,
                md5="a" * 32,
                source_archive="a.zip",
                parse_status="extracted",
            )
            s.add(doc)
            await s.commit()
            return doc.id

    return _make


async def test_docx_paragraphs_body(seed_bidder_with_file, tmp_path: Path):
    path = make_real_docx(
        tmp_path / "a.docx",
        body_paragraphs=["段一", "段二"],
        header_text="公司名",
        table_rows=[["A", "B"], ["1", "2"]],
    )
    doc_id = await seed_bidder_with_file(path, ".docx")

    async with async_session() as s:
        await extract_content(s, doc_id)

    async with async_session() as s:
        blocks = (
            await s.execute(
                select(DocumentText).where(DocumentText.bid_document_id == doc_id)
            )
        ).scalars().all()
        locs = {b.location for b in blocks}
        assert "body" in locs
        assert "header" in locs
        assert "table_row" in locs
        doc = await s.get(BidDocument, doc_id)
        assert doc.parse_status == "identified"


async def test_docx_metadata_written(seed_bidder_with_file, tmp_path: Path):
    path = make_real_docx(
        tmp_path / "b.docx", body_paragraphs=["x"], author="张三"
    )
    doc_id = await seed_bidder_with_file(path, ".docx")
    async with async_session() as s:
        await extract_content(s, doc_id)

    async with async_session() as s:
        meta = await s.get(DocumentMetadata, doc_id)
        assert meta is not None
        assert meta.author == "张三"


async def test_xlsx_sheet_extracted(seed_bidder_with_file, tmp_path: Path):
    path = make_real_xlsx(
        tmp_path / "x.xlsx",
        sheets={"Sheet1": [["A", "B"], [1, 2]]},
    )
    doc_id = await seed_bidder_with_file(path, ".xlsx")
    async with async_session() as s:
        await extract_content(s, doc_id)

    async with async_session() as s:
        blocks = (
            await s.execute(
                select(DocumentText).where(DocumentText.bid_document_id == doc_id)
            )
        ).scalars().all()
        assert len(blocks) >= 1
        assert all(b.location == "sheet" for b in blocks)
        doc = await s.get(BidDocument, doc_id)
        assert doc.parse_status == "identified"


async def test_pdf_marked_skipped(seed_bidder_with_file, tmp_path: Path):
    # 构造一个占位 "pdf" 文件
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-1.0\nfake")
    doc_id = await seed_bidder_with_file(path, ".pdf")
    async with async_session() as s:
        await extract_content(s, doc_id)

    async with async_session() as s:
        doc = await s.get(BidDocument, doc_id)
        assert doc.parse_status == "skipped"
        assert "pdf" in (doc.parse_error or "").lower()
        # 不写 document_texts
        blocks = (
            await s.execute(
                select(DocumentText).where(DocumentText.bid_document_id == doc_id)
            )
        ).scalars().all()
        assert blocks == []


async def test_broken_docx_identify_failed(seed_bidder_with_file, tmp_path: Path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not a real docx")
    doc_id = await seed_bidder_with_file(bad, ".docx")
    async with async_session() as s:
        await extract_content(s, doc_id)

    async with async_session() as s:
        doc = await s.get(BidDocument, doc_id)
        assert doc.parse_status == "identify_failed"
        assert doc.parse_error


async def test_missing_file_identify_failed(seed_bidder_with_file, tmp_path: Path):
    path = tmp_path / "gone.docx"
    path.write_text("placeholder")
    doc_id = await seed_bidder_with_file(path, ".docx")
    path.unlink()  # 删物理文件,extract 时查不到

    async with async_session() as s:
        await extract_content(s, doc_id)

    async with async_session() as s:
        doc = await s.get(BidDocument, doc_id)
        assert doc.parse_status == "identify_failed"


async def test_re_extract_clears_prior_records(
    seed_bidder_with_file, tmp_path: Path
):
    path = make_real_docx(tmp_path / "r.docx", body_paragraphs=["一"])
    doc_id = await seed_bidder_with_file(path, ".docx")
    async with async_session() as s:
        await extract_content(s, doc_id)
    # 第一次
    async with async_session() as s:
        cnt1 = (
            await s.execute(
                select(DocumentText).where(DocumentText.bid_document_id == doc_id)
            )
        ).scalars().all()
    # 再跑一次不应重复
    async with async_session() as s:
        await extract_content(s, doc_id)
    async with async_session() as s:
        cnt2 = (
            await s.execute(
                select(DocumentText).where(DocumentText.bid_document_id == doc_id)
            )
        ).scalars().all()
    assert len(cnt2) == len(cnt1)
