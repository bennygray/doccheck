"""L1 - alembic 0007_add_document_metadata_template 与 DocumentMetadata.template 可空。

验证:
- 迁移模块 revision id / down_revision 正确,不会意外变更
- DocumentMetadata.template 字段在 SQLite 测试环境下可空、可写字符串、可写 None
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_metadata import DocumentMetadata
from app.models.project import Project
from app.models.user import User


def _load_migration():
    """Load the 0007 alembic migration module by file path.

    alembic/versions 不是 Python package,不能直接 import。
    """
    backend_root = Path(__file__).resolve().parents[2]
    mig_file = (
        backend_root
        / "alembic"
        / "versions"
        / "0007_add_document_metadata_template.py"
    )
    assert mig_file.exists(), f"migration file missing: {mig_file}"
    spec = importlib.util.spec_from_file_location(
        "mig_0007", str(mig_file)
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_migration_identifiers() -> None:
    mod = _load_migration()
    assert mod.revision == "0007_add_doc_meta_template"
    assert mod.down_revision == "0006_add_document_sheets"
    # upgrade / downgrade 都应存在
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)


@pytest_asyncio.fixture
async def clean_meta_data():
    async with async_session() as session:
        for M in (DocumentMetadata, BidDocument, Bidder, Project, User):
            await session.execute(delete(M).where(M.bid_document_id > 0) if M is DocumentMetadata else delete(M).where(M.id > 0))
        await session.commit()
    yield
    async with async_session() as session:
        for M in (DocumentMetadata, BidDocument, Bidder, Project, User):
            await session.execute(delete(M).where(M.bid_document_id > 0) if M is DocumentMetadata else delete(M).where(M.id > 0))
        await session.commit()


async def _seed_doc() -> int:
    async with async_session() as session:
        user = User(
            username=f"alb7_{id(session)}",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        session.add(user)
        await session.flush()
        project = Project(name="P-alb7", owner_id=user.id)
        session.add(project)
        await session.flush()
        bidder = Bidder(
            name="B-alb7", project_id=project.id, parse_status="extracted"
        )
        session.add(bidder)
        await session.flush()
        doc = BidDocument(
            bidder_id=bidder.id,
            file_name="x.docx",
            file_path="/tmp/x.docx",
            file_size=1,
            file_type=".docx",
            md5=("a" * 32),
            source_archive="a.zip",
            parse_status="identified",
        )
        session.add(doc)
        await session.flush()
        await session.commit()
        return doc.id


@pytest.mark.asyncio
async def test_template_nullable(clean_meta_data):
    doc_id = await _seed_doc()
    async with async_session() as session:
        session.add(
            DocumentMetadata(
                bid_document_id=doc_id,
                author="张三",
                template=None,  # 显式 None
            )
        )
        await session.commit()

        row = (
            await session.execute(
                select(DocumentMetadata).where(
                    DocumentMetadata.bid_document_id == doc_id
                )
            )
        ).scalar_one()
    assert row.template is None
    assert row.author == "张三"


@pytest.mark.asyncio
async def test_template_stores_string(clean_meta_data):
    doc_id = await _seed_doc()
    async with async_session() as session:
        session.add(
            DocumentMetadata(
                bid_document_id=doc_id,
                template="Normal.dotm",
            )
        )
        await session.commit()

        row = (
            await session.execute(
                select(DocumentMetadata).where(
                    DocumentMetadata.bid_document_id == doc_id
                )
            )
        ).scalar_one()
    assert row.template == "Normal.dotm"
