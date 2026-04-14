"""L1 - _preflight_helpers.bidder_has_metadata 的 machine 分支扩 template (C10)

C10 新增:machine 判定 OR 条件包括 template 字段。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_metadata import DocumentMetadata
from app.models.project import Project
from app.models.user import User
from app.services.detect.agents._preflight_helpers import bidder_has_metadata


@pytest_asyncio.fixture
async def clean_ph():
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


async def _seed_bidder_with_meta(meta_kwargs: dict) -> int:
    async with async_session() as s:
        user = User(
            username=f"ph_{id(s)}",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        s.add(user)
        await s.flush()
        project = Project(name="Pph", owner_id=user.id)
        s.add(project)
        await s.flush()
        bidder = Bidder(name="Bph", project_id=project.id, parse_status="extracted")
        s.add(bidder)
        await s.flush()
        doc = BidDocument(
            bidder_id=bidder.id,
            file_name="x.docx",
            file_path="/tmp/x.docx",
            file_size=1,
            file_type=".docx",
            md5=("p" * 32),
            source_archive="a.zip",
            parse_status="identified",
        )
        s.add(doc)
        await s.flush()
        s.add(DocumentMetadata(bid_document_id=doc.id, **meta_kwargs))
        await s.commit()
        return bidder.id


@pytest.mark.asyncio
async def test_machine_passes_with_template_only(clean_ph):
    """app_name/app_version 全空但 template 非空 → machine preflight 通过。"""
    bidder_id = await _seed_bidder_with_meta(
        {"app_name": None, "app_version": None, "template": "Normal.dotm"}
    )
    async with async_session() as s:
        assert await bidder_has_metadata(s, bidder_id, "machine") is True


@pytest.mark.asyncio
async def test_machine_passes_with_app_name_only(clean_ph):
    bidder_id = await _seed_bidder_with_meta(
        {"app_name": "Word", "app_version": None, "template": None}
    )
    async with async_session() as s:
        assert await bidder_has_metadata(s, bidder_id, "machine") is True


@pytest.mark.asyncio
async def test_machine_fails_with_all_three_null(clean_ph):
    bidder_id = await _seed_bidder_with_meta(
        {"app_name": None, "app_version": None, "template": None}
    )
    async with async_session() as s:
        assert await bidder_has_metadata(s, bidder_id, "machine") is False


@pytest.mark.asyncio
async def test_author_branch_unchanged(clean_ph):
    """author 分支不受 C10 改动影响。"""
    bidder_id = await _seed_bidder_with_meta(
        {"author": "张三", "app_name": None, "template": None}
    )
    async with async_session() as s:
        assert await bidder_has_metadata(s, bidder_id, "author") is True
