"""L1 - metadata_impl/extractor (C10)"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_metadata import DocumentMetadata
from app.models.project import Project
from app.models.user import User
from app.services.detect.agents.metadata_impl.extractor import (
    extract_bidder_metadata,
)


@pytest_asyncio.fixture
async def clean_meta():
    async with async_session() as s:
        await s.execute(delete(DocumentMetadata).where(DocumentMetadata.bid_document_id > 0))
        for M in (BidDocument, Bidder, Project, User):
            await s.execute(delete(M).where(M.id > 0))
        await s.commit()
    yield
    async with async_session() as s:
        await s.execute(delete(DocumentMetadata).where(DocumentMetadata.bid_document_id > 0))
        for M in (BidDocument, Bidder, Project, User):
            await s.execute(delete(M).where(M.id > 0))
        await s.commit()


async def _seed_bidder_with_metas(metas: list[dict]) -> int:
    """Seed 一个 bidder,附加给定 meta 列表(每条 meta dict 对应一份 doc)。"""
    async with async_session() as s:
        user = User(
            username=f"ex_{id(s)}",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        s.add(user)
        await s.flush()
        project = Project(name="Pex", owner_id=user.id)
        s.add(project)
        await s.flush()
        bidder = Bidder(name="Bex", project_id=project.id, parse_status="extracted")
        s.add(bidder)
        await s.flush()
        for i, meta in enumerate(metas):
            doc = BidDocument(
                bidder_id=bidder.id,
                file_name=f"f{i}.docx",
                file_path=f"/tmp/f{i}.docx",
                file_size=1,
                file_type=".docx",
                md5=(f"ex{i:02d}" + "x" * 30)[:32],
                source_archive="a.zip",
                parse_status="identified",
            )
            s.add(doc)
            await s.flush()
            s.add(DocumentMetadata(bid_document_id=doc.id, **meta))
        await s.commit()
        return bidder.id


@pytest.mark.asyncio
async def test_extractor_returns_normalized_records(clean_meta):
    bidder_id = await _seed_bidder_with_metas(
        [
            {
                "author": " 张三 ",  # 归一化后去空白
                "last_saved_by": "ZHANG San",  # casefold
                "company": "ＡＢＣ",  # NFKC 全角
                "template": "Normal.DOTM",
                "app_name": "Microsoft Office Word",
                "app_version": "16.0000",
                "doc_created_at": datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
                "doc_modified_at": datetime(2026, 3, 2, 10, 5, tzinfo=timezone.utc),
            }
        ]
    )
    async with async_session() as s:
        records = await extract_bidder_metadata(s, bidder_id)
    assert len(records) == 1
    r = records[0]
    assert r["author_norm"] == "张三"
    assert r["last_saved_by_norm"] == "zhang san"
    assert r["company_norm"] == "abc"
    assert r["template_norm"] == "normal.dotm"
    assert r["app_name"] == "microsoft office word"
    assert r["app_version"] == "16.0000"
    # 原值保留
    assert r["author_raw"] == " 张三 "
    assert r["template_raw"] == "Normal.DOTM"
    # 时间不归一化
    assert r["doc_modified_at"] == datetime(2026, 3, 2, 10, 5, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_extractor_empty_bidder(clean_meta):
    """bidder 无任何 BidDocument/DocumentMetadata 返 []。"""
    async with async_session() as s:
        user = User(
            username=f"empty_{id(s)}",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        s.add(user)
        await s.flush()
        project = Project(name="Pempty", owner_id=user.id)
        s.add(project)
        await s.flush()
        bidder = Bidder(
            name="only-bidder",
            project_id=project.id,
            parse_status="extracted",
        )
        s.add(bidder)
        await s.flush()
        await s.commit()
        bidder_id = bidder.id
    async with async_session() as s:
        records = await extract_bidder_metadata(s, bidder_id)
    assert records == []


@pytest.mark.asyncio
async def test_extractor_empty_strings_become_none(clean_meta):
    bidder_id = await _seed_bidder_with_metas(
        [
            {
                "author": "",  # 空串
                "company": "   ",  # 纯空白
                "template": None,
            }
        ]
    )
    async with async_session() as s:
        records = await extract_bidder_metadata(s, bidder_id)
    assert len(records) == 1
    r = records[0]
    assert r["author_norm"] is None
    assert r["company_norm"] is None
    assert r["template_norm"] is None


@pytest.mark.asyncio
async def test_extractor_multiple_docs(clean_meta):
    bidder_id = await _seed_bidder_with_metas(
        [
            {"author": "张三"},
            {"author": "李四"},
            {"author": "张三"},
        ]
    )
    async with async_session() as s:
        records = await extract_bidder_metadata(s, bidder_id)
    assert len(records) == 3
    authors = [r["author_norm"] for r in records]
    assert sorted(authors) == ["张三", "张三", "李四"]
