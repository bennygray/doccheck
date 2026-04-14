"""L1 - C10 回填脚本 backfill_document_metadata_template

覆盖:
- 幂等:首次回填 N 个,二次回填 0 个(SQL 过滤 template IS NULL)
- 错误隔离:单 doc extract_metadata 抛异常不中断,继续其他
- --dry-run:只扫不写
- 缺失 Template 节点的文档仍计入 success,template 保持 NULL
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_metadata import DocumentMetadata
from app.models.document_sheet import DocumentSheet
from app.models.project import Project
from app.models.user import User
from scripts import backfill_document_metadata_template as bf


_APP_XML_WITH_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>Microsoft Office Word</Application>
  <AppVersion>16.0000</AppVersion>
  <Template>{template}</Template>
</Properties>
"""

_APP_XML_NO_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>Microsoft Office Word</Application>
</Properties>
"""

_CORE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:creator>王五</dc:creator>
</cp:coreProperties>
"""


def _make_ooxml(out: Path, *, template_value: str | None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(out), "w") as zf:
        zf.writestr("docProps/core.xml", _CORE_XML)
        if template_value is not None:
            zf.writestr(
                "docProps/app.xml",
                _APP_XML_WITH_TEMPLATE.format(template=template_value),
            )
        else:
            zf.writestr("docProps/app.xml", _APP_XML_NO_TEMPLATE)
    return out


async def _seed_docs(
    session: AsyncSession, tmp_path: Path, n: int, *, template_value: str | None
) -> list[int]:
    """创建 n 个 docx + DocumentMetadata.template=NULL。"""
    user = User(
        username=f"bfmt_{id(session)}",
        password_hash="x",
        role="reviewer",
        login_fail_count=0,
    )
    session.add(user)
    await session.flush()
    project = Project(name="Pbfmt", owner_id=user.id)
    session.add(project)
    await session.flush()
    bidder = Bidder(
        name="Bbfmt", project_id=project.id, parse_status="extracted"
    )
    session.add(bidder)
    await session.flush()

    doc_ids: list[int] = []
    for i in range(n):
        path = _make_ooxml(
            tmp_path / f"bfmt_{i}.docx", template_value=template_value
        )
        doc = BidDocument(
            bidder_id=bidder.id,
            file_name=path.name,
            file_path=str(path),
            file_size=path.stat().st_size,
            file_type=".docx",
            md5=(f"mt{i:02d}" + "x" * 30)[:32],
            source_archive="a.zip",
            parse_status="identified",
        )
        session.add(doc)
        await session.flush()
        # 预置 DocumentMetadata 行(template=NULL)
        session.add(
            DocumentMetadata(bid_document_id=doc.id, author="王五", template=None)
        )
        doc_ids.append(doc.id)
    await session.commit()
    return doc_ids


@pytest_asyncio.fixture
async def clean_bfmt_data():
    async with async_session() as s:
        for M in (
            DocumentSheet,
            DocumentMetadata,
            BidDocument,
            Bidder,
            Project,
            User,
        ):
            if M is DocumentMetadata:
                await s.execute(delete(M).where(M.bid_document_id > 0))
            else:
                await s.execute(delete(M).where(M.id > 0))
        await s.commit()
    yield
    async with async_session() as s:
        for M in (
            DocumentSheet,
            DocumentMetadata,
            BidDocument,
            Bidder,
            Project,
            User,
        ):
            if M is DocumentMetadata:
                await s.execute(delete(M).where(M.bid_document_id > 0))
            else:
                await s.execute(delete(M).where(M.id > 0))
        await s.commit()


@pytest.mark.asyncio
async def test_backfill_idempotent(clean_bfmt_data, tmp_path: Path):
    async with async_session() as s:
        await _seed_docs(s, tmp_path, n=3, template_value="Normal.dotm")

    total1, ok1, fail1 = await bf.main(dry_run=False)
    assert (total1, ok1, fail1) == (3, 3, 0)

    # 二次:已回填的 template 非 NULL → 过滤掉
    total2, ok2, fail2 = await bf.main(dry_run=False)
    assert (total2, ok2, fail2) == (0, 0, 0)

    async with async_session() as s:
        rows = (
            await s.execute(select(DocumentMetadata.template))
        ).scalars().all()
    assert rows == ["Normal.dotm", "Normal.dotm", "Normal.dotm"]


@pytest.mark.asyncio
async def test_backfill_error_isolation(
    clean_bfmt_data, tmp_path: Path, monkeypatch
):
    async with async_session() as s:
        doc_ids = await _seed_docs(
            s, tmp_path, n=3, template_value="Normal.dotm"
        )

    real_extract = bf.extract_metadata

    def fake_extract(file_path):
        if "bfmt_1.docx" in str(file_path):
            raise RuntimeError("corrupted")
        return real_extract(file_path)

    monkeypatch.setattr(bf, "extract_metadata", fake_extract)

    total, ok, fail = await bf.main(dry_run=False)
    assert (total, ok, fail) == (3, 2, 1)

    async with async_session() as s:
        rows = {
            row.bid_document_id: row.template
            for row in (
                await s.execute(select(DocumentMetadata))
            ).scalars().all()
        }
    # 失败的 doc 仍保持 NULL
    assert rows[doc_ids[1]] is None
    assert rows[doc_ids[0]] == "Normal.dotm"
    assert rows[doc_ids[2]] == "Normal.dotm"


@pytest.mark.asyncio
async def test_backfill_dry_run(clean_bfmt_data, tmp_path: Path):
    async with async_session() as s:
        await _seed_docs(s, tmp_path, n=2, template_value="Normal.dotm")

    total, ok, fail = await bf.main(dry_run=True)
    assert (total, ok, fail) == (2, 0, 0)

    async with async_session() as s:
        rows = (
            await s.execute(select(DocumentMetadata.template))
        ).scalars().all()
    assert rows == [None, None]


@pytest.mark.asyncio
async def test_backfill_template_missing_counts_success(
    clean_bfmt_data, tmp_path: Path
):
    """app.xml 无 Template 节点 — 仍 success,template 保持 NULL。"""
    async with async_session() as s:
        await _seed_docs(s, tmp_path, n=2, template_value=None)

    total, ok, fail = await bf.main(dry_run=False)
    assert (total, ok, fail) == (2, 2, 0)

    async with async_session() as s:
        rows = (
            await s.execute(select(DocumentMetadata.template))
        ).scalars().all()
    # UPDATE template = None;保持 NULL(但第二次扫 total 仍会扫到这 2 行因为过滤 IS NULL)
    assert rows == [None, None]
