"""L2: 加密压缩包密码重试 (C4 file-upload §11.6)。

覆盖 spec.md "加密压缩包密码重试" Requirement 的 4 个 Scenario。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.services.extract import extract_archive

from ..fixtures.archive_fixtures import make_encrypted_7z, md5_of
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
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "extracted_dir", str(tmp_path / "extracted"))
    (tmp_path / "uploads").mkdir()
    (tmp_path / "extracted").mkdir()
    return tmp_path


async def _setup_encrypted(seeded_reviewer, isolated_dirs, password="secret"):
    archive = make_encrypted_7z(
        isolated_dirs / "uploads" / "enc.7z", password=password
    )
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id)
    md5 = md5_of(archive)
    doc = await seed_archive_doc(
        bidder_id=bidder.id,
        archive_path=archive,
        md5=md5,
        file_name=archive.name,
        file_type=".7z",
    )
    return bidder, doc


async def test_encrypted_archive_detected(seeded_reviewer, isolated_dirs):
    bidder, doc = await _setup_encrypted(seeded_reviewer, isolated_dirs)

    await extract_archive(bidder.id)

    async with async_session() as s:
        archive_row = await s.get(BidDocument, doc.id)
    assert archive_row.parse_status == "needs_password"
    assert archive_row.parse_error  # 含"密码"或"加密"提示


async def test_correct_password_decrypts(
    seeded_reviewer, reviewer_token, auth_client, isolated_dirs
):
    bidder, doc = await _setup_encrypted(seeded_reviewer, isolated_dirs)
    # 先跑一次让它进 needs_password
    await extract_archive(bidder.id)

    client = await auth_client(reviewer_token)
    r = await client.post(
        f"/api/documents/{doc.id}/decrypt", json={"password": "secret"}
    )
    assert r.status_code == 202

    # 手动 await 一次"重试"
    await extract_archive(bidder.id, password="secret")

    async with async_session() as s:
        archive_row = await s.get(BidDocument, doc.id)
    assert archive_row.parse_status in {"extracted", "partial"}


async def test_wrong_password_keeps_needs_password(
    seeded_reviewer, reviewer_token, auth_client, isolated_dirs
):
    bidder, doc = await _setup_encrypted(seeded_reviewer, isolated_dirs)
    await extract_archive(bidder.id)

    client = await auth_client(reviewer_token)
    r = await client.post(
        f"/api/documents/{doc.id}/decrypt", json={"password": "wrong"}
    )
    # decrypt 端点本身只触发,不直接报密码错;202 + 后续状态保持 needs_password
    assert r.status_code == 202

    await extract_archive(bidder.id, password="wrong")

    async with async_session() as s:
        archive_row = await s.get(BidDocument, doc.id)
    assert archive_row.parse_status == "needs_password"


async def test_decrypt_on_non_needs_password_returns_409(
    seeded_reviewer, reviewer_token, auth_client, isolated_dirs
):
    """对已 extracted / failed 状态调 decrypt → 409。"""
    archive = isolated_dirs / "uploads" / "x.7z"
    archive.write_bytes(b"\x37\x7a\xbc\xaf\x27\x1c" + b"\x00" * 50)  # 假 7z 头
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    bidder = await seed_bidder(project_id=project.id, parse_status="extracted")
    doc = await seed_archive_doc(
        bidder_id=bidder.id,
        archive_path=archive,
        md5="a" * 32,
        file_type=".7z",
        parse_status="extracted",
    )
    client = await auth_client(reviewer_token)
    r = await client.post(
        f"/api/documents/{doc.id}/decrypt", json={"password": "any"}
    )
    assert r.status_code == 409
