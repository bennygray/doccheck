"""L1 - DocumentSheet 模型测试 (C9)

覆盖:建模字段 / unique (bid_document_id, sheet_index) 约束 / JSONB roundtrip。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_sheet import DocumentSheet
from app.models.project import Project
from app.models.user import User


async def _seed_doc(session: AsyncSession) -> int:
    user = User(
        username=f"ds_{id(session)}",
        password_hash="x",
        role="reviewer",
        login_fail_count=0,
    )
    session.add(user)
    await session.flush()

    project = Project(name="P-ds", owner_id=user.id)
    session.add(project)
    await session.flush()

    bidder = Bidder(
        name="Bid-ds", project_id=project.id, parse_status="extracted"
    )
    session.add(bidder)
    await session.flush()

    doc = BidDocument(
        bidder_id=bidder.id,
        file_name="quote.xlsx",
        file_path="/tmp/quote.xlsx",
        file_size=1024,
        file_type=".xlsx",
        md5=("a" * 32),
        source_archive="a.zip",
        parse_status="identified",
    )
    session.add(doc)
    await session.flush()
    await session.commit()
    return doc.id


@pytest_asyncio.fixture
async def clean_ds_data():
    async with async_session() as session:
        for M in (DocumentSheet, BidDocument, Bidder, Project, User):
            await session.execute(delete(M).where(M.id > 0))
        await session.commit()
    yield
    async with async_session() as session:
        for M in (DocumentSheet, BidDocument, Bidder, Project, User):
            await session.execute(delete(M).where(M.id > 0))
        await session.commit()


@pytest.mark.asyncio
async def test_document_sheet_insert_and_fields(clean_ds_data):
    async with async_session() as session:
        doc_id = await _seed_doc(session)
        rows = [["name", "qty", "price"], ["pump", 10, 500.5], ["pipe", None, 12]]
        session.add(
            DocumentSheet(
                bid_document_id=doc_id,
                sheet_index=0,
                sheet_name="报价汇总",
                hidden=False,
                rows_json=rows,
                merged_cells_json=["A1:C1"],
            )
        )
        await session.commit()

        row = (
            await session.execute(
                select(DocumentSheet).where(DocumentSheet.bid_document_id == doc_id)
            )
        ).scalar_one()
    assert row.sheet_index == 0
    assert row.sheet_name == "报价汇总"
    assert row.hidden is False
    assert row.rows_json == rows
    assert row.merged_cells_json == ["A1:C1"]
    assert row.created_at is not None


@pytest.mark.asyncio
async def test_document_sheet_unique_constraint(clean_ds_data):
    async with async_session() as session:
        doc_id = await _seed_doc(session)
        session.add(
            DocumentSheet(
                bid_document_id=doc_id,
                sheet_index=0,
                sheet_name="s1",
                rows_json=[["a"]],
                merged_cells_json=[],
            )
        )
        session.add(
            DocumentSheet(
                bid_document_id=doc_id,
                sheet_index=0,  # 重复 (doc_id, 0)
                sheet_name="s1-dup",
                rows_json=[["b"]],
                merged_cells_json=[],
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_document_sheet_jsonb_roundtrip(clean_ds_data):
    """各种 Python 原生类型能保真 roundtrip。"""
    async with async_session() as session:
        doc_id = await _seed_doc(session)
        rows = [
            ["张三", 2026, True, None],
            ["李四", 3.14, False, "备注"],
            [None, None, None, None],
        ]
        merged = ["A1:B2", "C3:E5", "F1:F10"]
        session.add(
            DocumentSheet(
                bid_document_id=doc_id,
                sheet_index=1,
                sheet_name="隐藏表",
                hidden=True,
                rows_json=rows,
                merged_cells_json=merged,
            )
        )
        await session.commit()

        row = (
            await session.execute(
                select(DocumentSheet).where(
                    DocumentSheet.bid_document_id == doc_id,
                    DocumentSheet.sheet_index == 1,
                )
            )
        ).scalar_one()
    assert row.rows_json == rows
    assert row.merged_cells_json == merged
    assert row.hidden is True
