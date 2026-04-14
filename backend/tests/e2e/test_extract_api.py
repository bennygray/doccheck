"""L2: 压缩包安全解压 (C4 file-upload §11.5)。

覆盖 spec.md "压缩包安全解压" Requirement 的 9 个 Scenario。
INFRA_DISABLE_EXTRACT=1 + 手动 await extract_archive,断言 DB 状态。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.services.extract import extract_archive

from ..fixtures.archive_fixtures import (
    make_broken_zip,
    make_empty_zip,
    make_gbk_zip,
    make_nested_zip,
    make_normal_zip,
    make_zip_slip_zip,
    md5_of,
)
from ._c4_helpers import seed_archive_doc, seed_bidder, seed_project


@pytest.fixture(autouse=True)
def _disable_auto_extract():
    prev = os.environ.get("INFRA_DISABLE_EXTRACT")
    os.environ["INFRA_DISABLE_EXTRACT"] = "1"
    yield
    if prev is None:
        os.environ.pop("INFRA_DISABLE_EXTRACT", None)
    else:
        os.environ["INFRA_DISABLE_EXTRACT"] = prev


@pytest.fixture
def isolated_dirs(tmp_path: Path, monkeypatch):
    """每个 extract 测试隔离 uploads / extracted 目录,避免污染。"""
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "extracted_dir", str(tmp_path / "extracted"))
    (tmp_path / "uploads").mkdir()
    (tmp_path / "extracted").mkdir()
    return tmp_path


async def _setup_bidder_with_archive(
    *, owner_id: int, archive: Path, file_type: str = ".zip"
) -> tuple[Bidder, BidDocument]:
    project = await seed_project(owner_id=owner_id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    md5 = md5_of(archive)
    doc = await seed_archive_doc(
        bidder_id=bidder.id,
        archive_path=archive,
        md5=md5,
        file_name=archive.name,
        file_type=file_type,
    )
    return bidder, doc


async def _reload_bidder(bidder_id: int) -> Bidder:
    async with async_session() as s:
        return (
            await s.execute(select(Bidder).where(Bidder.id == bidder_id))
        ).scalar_one()


async def _children_of(bidder_id: int) -> list[BidDocument]:
    """非"顶层归档行"的所有 bid_documents:解压条目 + 跳过条目都算。

    顶层归档行 = parse_status in {pending, extracting, extracted, partial,
    failed, needs_password} 的 .zip/.7z/.rar 行(由 seed/upload 显式建)。
    跳过的 nested 归档(parse_status=skipped)也用 .zip 后缀,但是 child。
    """
    async with async_session() as s:
        return (
            await s.execute(
                select(BidDocument).where(
                    BidDocument.bidder_id == bidder_id,
                    ~(
                        BidDocument.file_type.in_({".zip", ".7z", ".rar"})
                        & BidDocument.parse_status.in_(
                            {"pending", "extracting", "extracted", "partial",
                             "failed", "needs_password"}
                        )
                    ),
                )
            )
        ).scalars().all()


async def test_normal_zip_extracts(seeded_reviewer, isolated_dirs):
    archive = make_normal_zip(isolated_dirs / "uploads" / "x.zip")
    bidder, _ = await _setup_bidder_with_archive(
        owner_id=seeded_reviewer.id, archive=archive
    )

    await extract_archive(bidder.id)

    bidder_after = await _reload_bidder(bidder.id)
    assert bidder_after.parse_status in {"extracted", "partial"}
    children = await _children_of(bidder.id)
    # 3 entry: docx + xlsx + jpg → 全 extracted(无 skipped)
    assert {c.file_type for c in children} >= {".docx", ".xlsx", ".jpg"}
    assert all(c.parse_status == "extracted" for c in children)


async def test_zip_slip_entry_skipped(seeded_reviewer, isolated_dirs):
    archive = make_zip_slip_zip(isolated_dirs / "uploads" / "evil.zip")
    bidder, _ = await _setup_bidder_with_archive(
        owner_id=seeded_reviewer.id, archive=archive
    )

    await extract_archive(bidder.id)

    children = await _children_of(bidder.id)
    skipped = [c for c in children if c.parse_status == "skipped"]
    assert any("不安全" in (c.parse_error or "") for c in skipped)
    extracted = [c for c in children if c.parse_status == "extracted"]
    assert any(c.file_name == "ok.docx" for c in extracted)


async def test_size_budget_exceeded_fails(
    seeded_reviewer, isolated_dirs, monkeypatch
):
    from app.services.extract import safety

    monkeypatch.setattr(safety, "MAX_TOTAL_EXTRACTED_BYTES", 50)
    archive = make_normal_zip(isolated_dirs / "uploads" / "x.zip")
    bidder, doc = await _setup_bidder_with_archive(
        owner_id=seeded_reviewer.id, archive=archive
    )

    await extract_archive(bidder.id)

    async with async_session() as s:
        archive_row = await s.get(BidDocument, doc.id)
    assert archive_row.parse_status == "failed"
    assert "过大" in (archive_row.parse_error or "") or "2GB" in (
        archive_row.parse_error or ""
    )


async def test_count_budget_exceeded_fails(
    seeded_reviewer, isolated_dirs, monkeypatch
):
    from app.services.extract import safety

    monkeypatch.setattr(safety, "MAX_ENTRY_COUNT", 1)
    archive = make_normal_zip(isolated_dirs / "uploads" / "x.zip")
    bidder, doc = await _setup_bidder_with_archive(
        owner_id=seeded_reviewer.id, archive=archive
    )

    await extract_archive(bidder.id)

    async with async_session() as s:
        archive_row = await s.get(BidDocument, doc.id)
    assert archive_row.parse_status == "failed"
    assert "1" in (archive_row.parse_error or "")


async def test_nested_depth_exceeded_skipped(seeded_reviewer, isolated_dirs):
    """4 层嵌套 → 第 4 层应被 check_nesting_depth 拦下。"""
    archive = make_nested_zip(isolated_dirs / "uploads" / "n.zip", depth=4)
    bidder, _ = await _setup_bidder_with_archive(
        owner_id=seeded_reviewer.id, archive=archive
    )

    await extract_archive(bidder.id)

    children = await _children_of(bidder.id)
    skipped = [c for c in children if c.parse_status == "skipped"]
    assert any("嵌套" in (c.parse_error or "") for c in skipped)


async def test_gbk_filename_decoded(seeded_reviewer, isolated_dirs):
    archive = make_gbk_zip(isolated_dirs / "uploads" / "g.zip")
    bidder, _ = await _setup_bidder_with_archive(
        owner_id=seeded_reviewer.id, archive=archive
    )

    await extract_archive(bidder.id)

    children = await _children_of(bidder.id)
    names = {c.file_name for c in children}
    assert "投标文件.docx" in names


async def test_broken_zip_fails(seeded_reviewer, isolated_dirs):
    archive = make_broken_zip(isolated_dirs / "uploads" / "broken.zip")
    bidder, doc = await _setup_bidder_with_archive(
        owner_id=seeded_reviewer.id, archive=archive
    )

    await extract_archive(bidder.id)

    async with async_session() as s:
        archive_row = await s.get(BidDocument, doc.id)
    assert archive_row.parse_status == "failed"
    assert "损坏" in (archive_row.parse_error or "")


async def test_empty_zip_fails(seeded_reviewer, isolated_dirs):
    archive = make_empty_zip(isolated_dirs / "uploads" / "empty.zip")
    bidder, doc = await _setup_bidder_with_archive(
        owner_id=seeded_reviewer.id, archive=archive
    )

    await extract_archive(bidder.id)

    async with async_session() as s:
        archive_row = await s.get(BidDocument, doc.id)
    assert archive_row.parse_status == "failed"
    assert "无有效" in (archive_row.parse_error or "")


async def test_unsupported_file_type_skipped(seeded_reviewer, isolated_dirs):
    """ZIP 内含 .pdf → bid_documents 行 status=skipped,不影响其他文件。"""
    import zipfile

    archive = isolated_dirs / "uploads" / "mixed.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ok.docx", b"PK-doc-stub")
        zf.writestr("report.pdf", b"%PDF-stub")

    bidder, _ = await _setup_bidder_with_archive(
        owner_id=seeded_reviewer.id, archive=archive
    )

    await extract_archive(bidder.id)

    children = await _children_of(bidder.id)
    pdf_rows = [c for c in children if c.file_type == ".pdf"]
    assert pdf_rows
    assert all(c.parse_status == "skipped" for c in pdf_rows)
    assert all("不支持" in (c.parse_error or "") for c in pdf_rows)
