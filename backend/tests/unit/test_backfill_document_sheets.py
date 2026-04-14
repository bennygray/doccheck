"""L1 - C9 回填脚本 backfill_document_sheets (C9 §4)

覆盖:
- 幂等:首次回填 N 个,二次回填 0 个
- 错误隔离:单 doc extract_xlsx 抛异常不中断,继续其他 doc
- --dry-run:只扫不写(total>0, success=0, failed=0)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_sheet import DocumentSheet
from app.models.project import Project
from app.models.user import User
from scripts import backfill_document_sheets as bf
from tests.fixtures.doc_fixtures import make_real_xlsx


async def _seed_xlsx_docs(
    session: AsyncSession, tmp_path: Path, n: int
) -> list[int]:
    """创建 n 个真实 xlsx 的 BidDocument(不含 DocumentSheet)。"""
    user = User(
        username=f"bf_{id(session)}",
        password_hash="x",
        role="reviewer",
        login_fail_count=0,
    )
    session.add(user)
    await session.flush()
    project = Project(name="Pbf", owner_id=user.id)
    session.add(project)
    await session.flush()
    bidder = Bidder(
        name="Bbf", project_id=project.id, parse_status="extracted"
    )
    session.add(bidder)
    await session.flush()

    doc_ids: list[int] = []
    for i in range(n):
        path = make_real_xlsx(
            tmp_path / f"bf_{i}.xlsx",
            sheets={
                "S1": [["h1", "h2"], [1, 2]],
                "S2": [["a"], ["b"]],
            },
        )
        doc = BidDocument(
            bidder_id=bidder.id,
            file_name=path.name,
            file_path=str(path),
            file_size=path.stat().st_size,
            file_type=".xlsx",
            md5=(f"bf{i:02d}" + "x" * 30)[:32],
            source_archive="a.zip",
            parse_status="identified",
        )
        session.add(doc)
        await session.flush()
        doc_ids.append(doc.id)
    await session.commit()
    return doc_ids


@pytest_asyncio.fixture
async def clean_bf_data():
    async with async_session() as s:
        for M in (DocumentSheet, BidDocument, Bidder, Project, User):
            await s.execute(delete(M).where(M.id > 0))
        await s.commit()
    yield
    async with async_session() as s:
        for M in (DocumentSheet, BidDocument, Bidder, Project, User):
            await s.execute(delete(M).where(M.id > 0))
        await s.commit()


@pytest.mark.asyncio
async def test_backfill_idempotent(clean_bf_data, tmp_path: Path):
    async with async_session() as s:
        await _seed_xlsx_docs(s, tmp_path, n=3)

    total1, success1, failed1 = await bf.main(dry_run=False)
    assert total1 == 3
    assert success1 == 3
    assert failed1 == 0

    # 二次:已有 DocumentSheet → 扫到 0 个
    total2, success2, failed2 = await bf.main(dry_run=False)
    assert total2 == 0
    assert success2 == 0
    assert failed2 == 0

    # DocumentSheet 总数 = 3 doc × 2 sheet = 6(不重复插入)
    async with async_session() as s:
        cnt = len((await s.execute(select(DocumentSheet))).scalars().all())
    assert cnt == 6


@pytest.mark.asyncio
async def test_backfill_error_isolation(clean_bf_data, tmp_path: Path, monkeypatch):
    async with async_session() as s:
        doc_ids = await _seed_xlsx_docs(s, tmp_path, n=3)

    # mock extract_xlsx 让 doc_ids[1] 抛异常,其他正常
    real_extract = bf.extract_xlsx
    failing_id = doc_ids[1]

    def fake_extract(file_path):
        # file_path 形如 .../bf_1.xlsx,用 name 判
        if "bf_1.xlsx" in str(file_path):
            raise RuntimeError("corrupted file")
        return real_extract(file_path)

    monkeypatch.setattr(bf, "extract_xlsx", fake_extract)

    total, success, failed = await bf.main(dry_run=False)
    assert total == 3
    assert success == 2
    assert failed == 1

    async with async_session() as s:
        # 成功的 2 doc 各有 DocumentSheet;失败的没有
        ok_docs = (
            await s.execute(
                select(DocumentSheet.bid_document_id).distinct()
            )
        ).scalars().all()
    assert failing_id not in ok_docs
    assert len(ok_docs) == 2


@pytest.mark.asyncio
async def test_backfill_dry_run(clean_bf_data, tmp_path: Path):
    async with async_session() as s:
        await _seed_xlsx_docs(s, tmp_path, n=2)

    total, success, failed = await bf.main(dry_run=True)
    assert total == 2
    assert success == 0
    assert failed == 0
    async with async_session() as s:
        cnt = len((await s.execute(select(DocumentSheet))).scalars().all())
    assert cnt == 0  # dry-run 不写
