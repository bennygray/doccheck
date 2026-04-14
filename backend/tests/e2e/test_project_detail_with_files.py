"""L2: project-mgmt MODIFIED Requirement (C4 file-upload §11.9)。

覆盖 file-upload spec 的 project-mgmt MODIFIED Requirement 3 个 Scenario:
真实 bidders 摘要 / 空项目零进度 / 列表 risk_level 仍 null。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings

from ..fixtures.archive_fixtures import make_normal_zip, md5_of
from ._c4_helpers import seed_archive_doc, seed_bidder, seed_project


@pytest.fixture
def isolated_uploads(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()
    return tmp_path


async def test_detail_with_real_bidders(
    seeded_reviewer, reviewer_token, auth_client, isolated_uploads
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P")
    b1 = await seed_bidder(project_id=project.id, name="A")
    b2 = await seed_bidder(project_id=project.id, name="B")

    archive = make_normal_zip(isolated_uploads / "uploads" / "f.zip")
    await seed_archive_doc(bidder_id=b1.id, archive_path=archive, md5=md5_of(archive))
    client = await auth_client(reviewer_token)

    r = await client.get(f"/api/projects/{project.id}")
    assert r.status_code == 200
    body = r.json()
    assert len(body["bidders"]) == 2
    names = {b["name"] for b in body["bidders"]}
    assert names == {"A", "B"}
    assert body["progress"]["total_bidders"] == 2
    # b1 有 1 个 archive 文件
    assert any(f["bidder_id"] == b1.id for f in body["files"])


async def test_empty_project_zero_progress(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="empty")
    client = await auth_client(reviewer_token)

    r = await client.get(f"/api/projects/{project.id}")
    body = r.json()
    assert body["bidders"] == []
    assert body["files"] == []
    assert body["progress"] == {
        "total_bidders": 0,
        "pending_count": 0,
        "extracting_count": 0,
        "extracted_count": 0,
        "identifying_count": 0,
        "identified_count": 0,
        "pricing_count": 0,
        "priced_count": 0,
        "partial_count": 0,
        "failed_count": 0,
        "needs_password_count": 0,
    }


async def test_list_items_still_have_null_risk_level(
    seeded_reviewer, reviewer_token, auth_client
):
    """C4 修了详情但列表的 risk_level 仍恒 null(C6 检测才填)。"""
    await seed_project(owner_id=seeded_reviewer.id, name="P1")
    await seed_project(owner_id=seeded_reviewer.id, name="P2")
    client = await auth_client(reviewer_token)

    r = await client.get("/api/projects/")
    items = r.json()["items"]
    for item in items:
        assert "risk_level" in item
        assert item["risk_level"] is None
