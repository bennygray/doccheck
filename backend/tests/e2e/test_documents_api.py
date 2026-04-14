"""L2: 文件列表 + 文件下载与删除 (C4 file-upload §11.7)。

覆盖 spec.md "文件列表与解析状态" (3 scenarios) + "文件下载与删除" (4 scenarios)。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session
from app.models.bid_document import BidDocument

from ..fixtures.archive_fixtures import make_normal_zip, md5_of
from ._c4_helpers import seed_archive_doc, seed_bidder, seed_project, seed_user


@pytest.fixture
def isolated_uploads(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()
    return tmp_path


# ============================================================ 文件列表

async def test_list_documents_returns_array(
    seeded_reviewer, reviewer_token, auth_client, isolated_uploads
):
    archive = make_normal_zip(isolated_uploads / "uploads" / "x.zip")
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    await seed_archive_doc(
        bidder_id=bidder.id, archive_path=archive, md5=md5_of(archive)
    )
    client = await auth_client(reviewer_token)

    r = await client.get(
        f"/api/projects/{project.id}/bidders/{bidder.id}/documents"
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    item = body[0]
    for f in (
        "id", "file_name", "file_path", "file_size", "file_type",
        "parse_status", "parse_error", "file_role", "md5", "created_at",
    ):
        assert f in item
    assert item["file_role"] is None  # C4 阶段恒 null


async def test_list_during_extracting_state(
    seeded_reviewer, reviewer_token, auth_client, isolated_uploads
):
    archive = make_normal_zip(isolated_uploads / "uploads" / "x.zip")
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id, parse_status="extracting")
    await seed_archive_doc(
        bidder_id=bidder.id,
        archive_path=archive,
        md5=md5_of(archive),
        parse_status="extracting",
    )
    client = await auth_client(reviewer_token)

    r = await client.get(
        f"/api/projects/{project.id}/bidders/{bidder.id}/documents"
    )
    assert r.status_code == 200
    # bidder 详情仍可查
    r2 = await client.get(
        f"/api/projects/{project.id}/bidders/{bidder.id}"
    )
    assert r2.json()["parse_status"] == "extracting"


async def test_list_documents_cross_user_404(
    seeded_reviewer, reviewer_token, auth_client, isolated_uploads
):
    other = await seed_user("other-r", "reviewer")
    other_proj = await seed_project(owner_id=other.id, name="op")
    other_bidder = await seed_bidder(project_id=other_proj.id, name="O")
    client = await auth_client(reviewer_token)

    r = await client.get(
        f"/api/projects/{other_proj.id}/bidders/{other_bidder.id}/documents"
    )
    assert r.status_code == 404


# ============================================================ 下载与删除

async def test_download_returns_file_stream(
    seeded_reviewer, reviewer_token, auth_client, isolated_uploads
):
    archive = make_normal_zip(isolated_uploads / "uploads" / "src.zip")
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    doc = await seed_archive_doc(
        bidder_id=bidder.id, archive_path=archive, md5=md5_of(archive)
    )
    client = await auth_client(reviewer_token)

    r = await client.get(f"/api/documents/{doc.id}/download")
    assert r.status_code == 200
    assert r.content == archive.read_bytes()


async def test_download_when_physical_missing_returns_410(
    seeded_reviewer, reviewer_token, auth_client, isolated_uploads
):
    archive = make_normal_zip(isolated_uploads / "uploads" / "vanish.zip")
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    doc = await seed_archive_doc(
        bidder_id=bidder.id, archive_path=archive, md5=md5_of(archive)
    )
    archive.unlink()  # 模拟生命周期任务清掉

    client = await auth_client(reviewer_token)
    r = await client.get(f"/api/documents/{doc.id}/download")
    assert r.status_code == 410


async def test_download_other_user_404(
    seeded_reviewer, reviewer_token, auth_client, isolated_uploads
):
    other = await seed_user("u-x", "reviewer")
    other_proj = await seed_project(owner_id=other.id, name="op")
    other_bidder = await seed_bidder(project_id=other_proj.id, name="O")
    archive = make_normal_zip(isolated_uploads / "uploads" / "x.zip")
    other_doc = await seed_archive_doc(
        bidder_id=other_bidder.id,
        archive_path=archive,
        md5=md5_of(archive),
    )

    client = await auth_client(reviewer_token)
    r = await client.get(f"/api/documents/{other_doc.id}/download")
    assert r.status_code == 404


async def test_delete_document_keeps_physical(
    seeded_reviewer, reviewer_token, auth_client, isolated_uploads
):
    archive = make_normal_zip(isolated_uploads / "uploads" / "x.zip")
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    doc = await seed_archive_doc(
        bidder_id=bidder.id, archive_path=archive, md5=md5_of(archive)
    )
    client = await auth_client(reviewer_token)

    r = await client.delete(f"/api/documents/{doc.id}")
    assert r.status_code == 204

    async with async_session() as s:
        rows = (
            await s.execute(
                select(BidDocument).where(BidDocument.id == doc.id)
            )
        ).scalars().all()
    assert rows == []
    assert archive.exists()  # 物理文件保留
