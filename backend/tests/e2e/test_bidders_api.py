"""L2: 投标人 CRUD (C4 file-upload §11.3)。

覆盖 spec.md "投标人 CRUD" Requirement 的 9 个 Scenario。
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.session import async_session
from app.models.bidder import Bidder

from ._c4_helpers import seed_bidder, seed_project, seed_user, token_for


async def test_create_bidder_name_only(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P1")
    client = await auth_client(reviewer_token)

    r = await client.post(
        f"/api/projects/{project.id}/bidders/",
        data={"name": "A 公司"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "A 公司"
    assert body["project_id"] == project.id
    assert body["parse_status"] == "pending"
    assert body["file_count"] == 0


async def test_create_bidder_duplicate_name_409(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P1")
    await seed_bidder(project_id=project.id, name="A 公司")
    client = await auth_client(reviewer_token)

    r = await client.post(
        f"/api/projects/{project.id}/bidders/", data={"name": "A 公司"}
    )
    assert r.status_code == 409


async def test_create_bidder_cross_project_same_name_ok(
    seeded_reviewer, reviewer_token, auth_client
):
    p1 = await seed_project(owner_id=seeded_reviewer.id, name="P1")
    p2 = await seed_project(owner_id=seeded_reviewer.id, name="P2")
    await seed_bidder(project_id=p1.id, name="A 公司")
    client = await auth_client(reviewer_token)

    r = await client.post(
        f"/api/projects/{p2.id}/bidders/", data={"name": "A 公司"}
    )
    assert r.status_code == 201


async def test_create_bidder_empty_name_422(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P1")
    client = await auth_client(reviewer_token)

    r = await client.post(
        f"/api/projects/{project.id}/bidders/", data={"name": ""}
    )
    assert r.status_code == 422


async def test_create_bidder_too_long_name_422(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P1")
    client = await auth_client(reviewer_token)

    r = await client.post(
        f"/api/projects/{project.id}/bidders/", data={"name": "x" * 201}
    )
    assert r.status_code == 422


async def test_reviewer_cannot_access_others_bidders_404(
    seeded_reviewer, reviewer_token, auth_client
):
    other = await seed_user("reviewer_other", "reviewer")
    other_proj = await seed_project(owner_id=other.id, name="other-P")
    await seed_bidder(project_id=other_proj.id, name="X")
    client = await auth_client(reviewer_token)

    # POST → 404
    r = await client.post(
        f"/api/projects/{other_proj.id}/bidders/", data={"name": "Y"}
    )
    assert r.status_code == 404
    # GET → 404
    r = await client.get(f"/api/projects/{other_proj.id}/bidders/")
    assert r.status_code == 404


async def test_admin_can_access_any_bidders(
    seeded_admin, admin_token, auth_client
):
    other = await seed_user("reviewer_other", "reviewer")
    proj = await seed_project(owner_id=other.id, name="proj")
    bidder = await seed_bidder(project_id=proj.id, name="A 公司")
    client = await auth_client(admin_token)

    r = await client.get(f"/api/projects/{proj.id}/bidders/")
    assert r.status_code == 200
    r = await client.get(f"/api/projects/{proj.id}/bidders/{bidder.id}")
    assert r.status_code == 200


async def test_delete_own_bidder_soft_deletes(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(owner_id=seeded_reviewer.id, name="P1")
    bidder = await seed_bidder(project_id=project.id, name="A 公司")
    client = await auth_client(reviewer_token)

    r = await client.delete(
        f"/api/projects/{project.id}/bidders/{bidder.id}"
    )
    assert r.status_code == 204

    async with async_session() as s:
        row = (
            await s.execute(select(Bidder).where(Bidder.id == bidder.id))
        ).scalar_one()
        assert row.deleted_at is not None


async def test_cannot_delete_bidder_when_project_analyzing_409(
    seeded_reviewer, reviewer_token, auth_client
):
    project = await seed_project(
        owner_id=seeded_reviewer.id, name="P-x", status_="analyzing"
    )
    bidder = await seed_bidder(project_id=project.id, name="A 公司")
    client = await auth_client(reviewer_token)

    r = await client.delete(
        f"/api/projects/{project.id}/bidders/{bidder.id}"
    )
    assert r.status_code == 409
