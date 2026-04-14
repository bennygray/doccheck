"""L2: 文件上传 (创建 + 追加) (C4 file-upload §11.4)。

覆盖 spec.md "文件上传(创建+追加)" Requirement 的 8 个 Scenario。
INFRA_DISABLE_EXTRACT=1 → trigger_extract no-op,断言聚焦在落盘 + DB 行,
extract 行为留给 test_extract_api.py。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session
from app.models.bid_document import BidDocument

from ..fixtures.archive_fixtures import make_normal_zip, md5_of
from ._c4_helpers import seed_bidder, seed_project


@pytest.fixture(autouse=True)
def _disable_auto_extract():
    """L2 上传层关心落盘和 DB,不关心 extract 协程是否自动起。"""
    prev = os.environ.get("INFRA_DISABLE_EXTRACT")
    os.environ["INFRA_DISABLE_EXTRACT"] = "1"
    yield
    if prev is None:
        os.environ.pop("INFRA_DISABLE_EXTRACT", None)
    else:
        os.environ["INFRA_DISABLE_EXTRACT"] = prev


async def _post_upload(client, project_id: int, bidder_id: int, archive_path: Path):
    with archive_path.open("rb") as fp:
        return await client.post(
            f"/api/projects/{project_id}/bidders/{bidder_id}/upload",
            files={"file": (archive_path.name, fp, "application/zip")},
        )


async def test_upload_normal_zip_201(
    seeded_reviewer, reviewer_token, auth_client, tmp_path
):
    archive = make_normal_zip(tmp_path / "ok.zip")
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    client = await auth_client(reviewer_token)

    r = await _post_upload(client, project.id, bidder.id, archive)
    assert r.status_code == 201
    body = r.json()
    assert body["bidder_id"] == bidder.id
    assert body["archive_filename"] == "ok.zip"
    assert len(body["new_files"]) == 1
    assert body["skipped_duplicates"] == []


async def test_upload_exe_rejected_415(
    seeded_reviewer, reviewer_token, auth_client, tmp_path
):
    archive = tmp_path / "virus.exe"
    archive.write_bytes(b"MZ\x90\x00" + b"\x00" * 100)
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    client = await auth_client(reviewer_token)

    r = await _post_upload(client, project.id, bidder.id, archive)
    assert r.status_code == 415


async def test_upload_fake_zip_extension_rejected_415(
    seeded_reviewer, reviewer_token, auth_client, tmp_path
):
    """改扩展名的 .exe → 魔数校验失败。"""
    archive = tmp_path / "fake.zip"
    archive.write_bytes(b"MZ\x90\x00" + b"\x00" * 100)  # PE 头
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    client = await auth_client(reviewer_token)

    r = await _post_upload(client, project.id, bidder.id, archive)
    assert r.status_code == 415


async def test_upload_too_large_413(
    seeded_reviewer, reviewer_token, auth_client, tmp_path, monkeypatch
):
    """模拟 >500MB:把 MAX_ARCHIVE_BYTES 暂设小,避免真造 500MB 文件。"""
    from app.services.upload import validator

    monkeypatch.setattr(validator, "MAX_ARCHIVE_BYTES", 100)

    archive = make_normal_zip(tmp_path / "big.zip")  # > 100 字节
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    client = await auth_client(reviewer_token)

    r = await _post_upload(client, project.id, bidder.id, archive)
    assert r.status_code == 413


async def test_same_bidder_duplicate_md5_skipped(
    seeded_reviewer, reviewer_token, auth_client, tmp_path
):
    archive = make_normal_zip(tmp_path / "x.zip")
    md5 = md5_of(archive)
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    client = await auth_client(reviewer_token)

    r1 = await _post_upload(client, project.id, bidder.id, archive)
    assert r1.status_code == 201
    r2 = await _post_upload(client, project.id, bidder.id, archive)
    assert r2.status_code == 201
    body = r2.json()
    assert body["new_files"] == []
    assert md5 in body["skipped_duplicates"]


async def test_cross_bidder_same_md5_kept(
    seeded_reviewer, reviewer_token, auth_client, tmp_path
):
    archive = make_normal_zip(tmp_path / "shared.zip")
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    b1 = await seed_bidder(project_id=project.id, name="A")
    b2 = await seed_bidder(project_id=project.id, name="B")
    client = await auth_client(reviewer_token)

    r1 = await _post_upload(client, project.id, b1.id, archive)
    r2 = await _post_upload(client, project.id, b2.id, archive)
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["new_files"]
    assert r2.json()["new_files"]


async def test_upload_to_missing_bidder_404(
    seeded_reviewer, reviewer_token, auth_client, tmp_path
):
    archive = make_normal_zip(tmp_path / "x.zip")
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    client = await auth_client(reviewer_token)

    r = await _post_upload(client, project.id, 99999, archive)
    assert r.status_code == 404


async def test_upload_persists_to_disk(
    seeded_reviewer, reviewer_token, auth_client, tmp_path, monkeypatch
):
    """上传后 uploads/{pid}/{bid}/<md5[:16]>_<name> 物理存在,大小 = 原文件。"""
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    archive = make_normal_zip(tmp_path / "ok.zip")
    expected_size = archive.stat().st_size
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    client = await auth_client(reviewer_token)

    r = await _post_upload(client, project.id, bidder.id, archive)
    assert r.status_code == 201

    async with async_session() as s:
        rows = (
            await s.execute(
                select(BidDocument).where(BidDocument.bidder_id == bidder.id)
            )
        ).scalars().all()
    assert len(rows) == 1
    saved = Path(rows[0].file_path)
    assert saved.exists()
    assert saved.stat().st_size == expected_size
