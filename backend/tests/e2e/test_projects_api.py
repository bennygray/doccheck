"""L2: 项目管理 API E2E (C3 project-mgmt).

覆盖 openspec/changes/project-mgmt/specs/project-mgmt/spec.md 的 7 个 Requirement
共 30 个 Scenario。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.db.session import async_session
from app.models.project import Project
from app.models.user import User
from app.services.auth.jwt import create_access_token
from app.services.auth.password import hash_password

# -----------------------------------------------------------------------------
# 共享工具
# -----------------------------------------------------------------------------


async def _clean_projects() -> None:
    async with async_session() as s:
        await s.execute(delete(Project))
        await s.commit()


def _token_for(user: User) -> str:
    return create_access_token(
        user_id=user.id,
        role=user.role,
        pwd_v=int(user.password_changed_at.timestamp() * 1000),
        username=user.username,
    )


async def _seed_user(username: str, role: str) -> User:
    async with async_session() as s:
        u = User(
            username=username,
            password_hash=hash_password("x" * 10 + "1"),
            role=role,
            is_active=True,
            must_change_password=False,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


async def _seed_project(
    *,
    owner_id: int,
    name: str,
    status_: str = "draft",
    risk_level: str | None = None,
    bid_code: str | None = None,
    deleted: bool = False,
) -> Project:
    async with async_session() as s:
        p = Project(
            name=name,
            owner_id=owner_id,
            status=status_,
            risk_level=risk_level,
            bid_code=bid_code,
            deleted_at=datetime.now(timezone.utc) if deleted else None,
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p


# -----------------------------------------------------------------------------
# Requirement 1: 创建项目 (6 scenarios)
# -----------------------------------------------------------------------------


async def test_create_project_success(seeded_reviewer, reviewer_token, auth_client):
    await _clean_projects()
    client = await auth_client(reviewer_token)
    r = await client.post(
        "/api/projects/",
        json={
            "name": "测试项目A",
            "bid_code": "BID-001",
            "max_price": "12345.67",
            "description": "desc",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "测试项目A"
    assert body["status"] == "draft"
    assert body["owner_id"] == seeded_reviewer.id
    assert body["risk_level"] is None
    assert body["deleted_at"] is None
    assert "id" in body and "created_at" in body


async def test_create_project_missing_name(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    client = await auth_client(reviewer_token)
    r = await client.post("/api/projects/", json={})
    assert r.status_code == 422


async def test_create_project_name_too_long(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    client = await auth_client(reviewer_token)
    r = await client.post("/api/projects/", json={"name": "x" * 101})
    assert r.status_code == 422


async def test_create_project_negative_max_price(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    client = await auth_client(reviewer_token)
    r = await client.post(
        "/api/projects/", json={"name": "x", "max_price": "-1"}
    )
    assert r.status_code == 422


async def test_create_project_same_name_allowed_twice(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    client = await auth_client(reviewer_token)
    r1 = await client.post("/api/projects/", json={"name": "同名"})
    r2 = await client.post("/api/projects/", json={"name": "同名"})
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]


async def test_create_project_without_token(seeded_reviewer, auth_client):
    await _clean_projects()
    client = await auth_client(None)
    r = await client.post("/api/projects/", json={"name": "x"})
    assert r.status_code == 401


# -----------------------------------------------------------------------------
# Requirement 2: 项目列表 (9 scenarios)
# -----------------------------------------------------------------------------


async def test_list_reviewer_sees_only_own(
    seeded_reviewer, reviewer_token, auth_client
):
    """reviewer A 看不到 reviewer B 的项目。"""
    await _clean_projects()
    user_b = await _seed_user("reviewerB", "reviewer")
    await _seed_project(owner_id=seeded_reviewer.id, name="A1")
    await _seed_project(owner_id=seeded_reviewer.id, name="A2")
    await _seed_project(owner_id=user_b.id, name="B1")
    await _seed_project(owner_id=user_b.id, name="B2")
    await _seed_project(owner_id=user_b.id, name="B3")

    client = await auth_client(reviewer_token)
    r = await client.get("/api/projects/")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert {i["name"] for i in body["items"]} == {"A1", "A2"}


async def test_list_admin_sees_all(seeded_admin, admin_token, auth_client):
    await _clean_projects()
    user_a = await _seed_user("reviewerA", "reviewer")
    user_b = await _seed_user("reviewerB", "reviewer")
    await _seed_project(owner_id=user_a.id, name="A1")
    await _seed_project(owner_id=user_a.id, name="A2")
    await _seed_project(owner_id=user_b.id, name="B1")
    await _seed_project(owner_id=user_b.id, name="B2")
    await _seed_project(owner_id=user_b.id, name="B3")

    client = await auth_client(admin_token)
    r = await client.get("/api/projects/")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5


async def test_list_excludes_soft_deleted(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    await _seed_project(owner_id=seeded_reviewer.id, name="alive-1")
    await _seed_project(owner_id=seeded_reviewer.id, name="alive-2")
    await _seed_project(owner_id=seeded_reviewer.id, name="dead", deleted=True)

    client = await auth_client(reviewer_token)
    r = await client.get("/api/projects/")
    body = r.json()
    assert body["total"] == 2
    assert {i["name"] for i in body["items"]} == {"alive-1", "alive-2"}


async def test_list_filter_by_status(seeded_reviewer, reviewer_token, auth_client):
    await _clean_projects()
    await _seed_project(owner_id=seeded_reviewer.id, name="d1", status_="draft")
    await _seed_project(owner_id=seeded_reviewer.id, name="d2", status_="draft")
    await _seed_project(
        owner_id=seeded_reviewer.id, name="a1", status_="analyzing"
    )

    client = await auth_client(reviewer_token)
    r = await client.get("/api/projects/?status=draft")
    body = r.json()
    assert body["total"] == 2
    assert all(i["status"] == "draft" for i in body["items"])


async def test_list_search_matches_name(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    await _seed_project(owner_id=seeded_reviewer.id, name="京沪高速投标")
    await _seed_project(owner_id=seeded_reviewer.id, name="市政道路")

    client = await auth_client(reviewer_token)
    r = await client.get("/api/projects/?search=高速")
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "京沪高速投标"


async def test_list_search_matches_bid_code(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    await _seed_project(
        owner_id=seeded_reviewer.id, name="未命名", bid_code="BID-2026-001"
    )
    await _seed_project(
        owner_id=seeded_reviewer.id, name="另一个", bid_code="OTHER-2025"
    )

    client = await auth_client(reviewer_token)
    r = await client.get("/api/projects/?search=BID-2026")
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["bid_code"] == "BID-2026-001"


async def test_list_pagination(seeded_reviewer, reviewer_token, auth_client):
    await _clean_projects()
    for i in range(15):
        await _seed_project(owner_id=seeded_reviewer.id, name=f"p{i:02}")

    client = await auth_client(reviewer_token)
    r = await client.get("/api/projects/?page=2&size=12")
    body = r.json()
    assert body["total"] == 15
    assert body["page"] == 2
    assert body["size"] == 12
    assert len(body["items"]) == 3


async def test_list_size_over_upper_bound_returns_422(
    seeded_reviewer, reviewer_token, auth_client
):
    """size 上限策略锁定:服务端返 422(拒绝),不自动截断。"""
    await _clean_projects()
    client = await auth_client(reviewer_token)
    r = await client.get("/api/projects/?size=500")
    assert r.status_code == 422


async def test_list_without_token(auth_client):
    client = await auth_client(None)
    r = await client.get("/api/projects/")
    assert r.status_code == 401


# -----------------------------------------------------------------------------
# Requirement 3: 项目详情 (5 scenarios)
# -----------------------------------------------------------------------------


async def test_detail_reviewer_sees_own(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    p = await _seed_project(owner_id=seeded_reviewer.id, name="my project")

    client = await auth_client(reviewer_token)
    r = await client.get(f"/api/projects/{p.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == p.id
    assert body["name"] == "my project"
    # C4 起 progress 由真实聚合产出;空项目所有计数 = 0(file-upload MODIFIED Req)
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


async def test_detail_reviewer_others_returns_404(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    user_b = await _seed_user("reviewerB", "reviewer")
    p = await _seed_project(owner_id=user_b.id, name="B project")

    client = await auth_client(reviewer_token)
    r = await client.get(f"/api/projects/{p.id}")
    assert r.status_code == 404


async def test_detail_admin_sees_any(seeded_admin, admin_token, auth_client):
    await _clean_projects()
    user_a = await _seed_user("reviewerA", "reviewer")
    p = await _seed_project(owner_id=user_a.id, name="A project")

    client = await auth_client(admin_token)
    r = await client.get(f"/api/projects/{p.id}")
    assert r.status_code == 200
    assert r.json()["name"] == "A project"


async def test_detail_soft_deleted_returns_404(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    p = await _seed_project(owner_id=seeded_reviewer.id, name="gone", deleted=True)

    client = await auth_client(reviewer_token)
    r = await client.get(f"/api/projects/{p.id}")
    assert r.status_code == 404


async def test_detail_nonexistent_returns_404(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    client = await auth_client(reviewer_token)
    r = await client.get("/api/projects/99999")
    assert r.status_code == 404


# -----------------------------------------------------------------------------
# Requirement 4: 软删除 (5 scenarios)
# -----------------------------------------------------------------------------


async def test_delete_reviewer_own_success(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    p = await _seed_project(owner_id=seeded_reviewer.id, name="to-delete")

    client = await auth_client(reviewer_token)
    r = await client.delete(f"/api/projects/{p.id}")
    assert r.status_code == 204

    # DB 里 deleted_at 已置值
    async with async_session() as s:
        row = (
            await s.execute(select(Project).where(Project.id == p.id))
        ).scalar_one()
        assert row.deleted_at is not None

    # 列表中不再出现
    r = await client.get("/api/projects/")
    assert r.status_code == 200
    assert r.json()["total"] == 0


async def test_delete_others_returns_404(
    seeded_reviewer, reviewer_token, auth_client
):
    """reviewer 删他人项目返 404,不返 403,不泄露项目存在性。"""
    await _clean_projects()
    user_b = await _seed_user("reviewerB", "reviewer")
    p = await _seed_project(owner_id=user_b.id, name="B's project")

    client = await auth_client(reviewer_token)
    r = await client.delete(f"/api/projects/{p.id}")
    assert r.status_code == 404

    # 对方项目 deleted_at 未被改动
    async with async_session() as s:
        row = (
            await s.execute(select(Project).where(Project.id == p.id))
        ).scalar_one()
        assert row.deleted_at is None


async def test_delete_analyzing_returns_409(
    seeded_reviewer, reviewer_token, auth_client
):
    """status=analyzing 拒删;C3 阶段用 fixture 手动置 status 触发。"""
    await _clean_projects()
    p = await _seed_project(
        owner_id=seeded_reviewer.id, name="busy", status_="analyzing"
    )

    client = await auth_client(reviewer_token)
    r = await client.delete(f"/api/projects/{p.id}")
    assert r.status_code == 409

    async with async_session() as s:
        row = (
            await s.execute(select(Project).where(Project.id == p.id))
        ).scalar_one()
        assert row.deleted_at is None


async def test_delete_admin_any(seeded_admin, admin_token, auth_client):
    await _clean_projects()
    user_a = await _seed_user("reviewerA", "reviewer")
    p = await _seed_project(owner_id=user_a.id, name="A's project")

    client = await auth_client(admin_token)
    r = await client.delete(f"/api/projects/{p.id}")
    assert r.status_code == 204


async def test_delete_already_deleted_returns_404(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    p = await _seed_project(
        owner_id=seeded_reviewer.id, name="twice", deleted=True
    )

    client = await auth_client(reviewer_token)
    r = await client.delete(f"/api/projects/{p.id}")
    assert r.status_code == 404


# -----------------------------------------------------------------------------
# Requirement 5: 角色与鉴权 (3 scenarios)
# -----------------------------------------------------------------------------


async def test_expired_token_returns_401(
    seeded_reviewer, reviewer_token, auth_client
):
    """用一个签名正确但过期的 token 调任一端点 → 401。

    直接伪造一个 exp=过去时间的 token。
    """
    from datetime import datetime, timedelta, timezone

    from jose import jwt as _jwt

    from app.core.config import settings

    expired_payload = {
        "sub": str(seeded_reviewer.id),
        "role": seeded_reviewer.role,
        "pwd_v": int(seeded_reviewer.password_changed_at.timestamp() * 1000),
        "username": seeded_reviewer.username,
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    expired = _jwt.encode(
        expired_payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    client = await auth_client(expired)

    r = await client.get("/api/projects/")
    assert r.status_code == 401
    r = await client.post("/api/projects/", json={"name": "x"})
    assert r.status_code == 401


async def test_pwd_v_mismatch_returns_401(
    seeded_reviewer, reviewer_token, auth_client
):
    """改密后 pwd_v 不再匹配 → 401。模拟改密直接改 DB。"""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    async with async_session() as s:
        # 将 password_changed_at 推向未来 1 分钟,使 reviewer_token 的 pwd_v 失效
        await s.execute(
            update(User)
            .where(User.id == seeded_reviewer.id)
            .values(password_changed_at=datetime.now(timezone.utc) + timedelta(minutes=1))
        )
        await s.commit()

    client = await auth_client(reviewer_token)
    r = await client.get("/api/projects/")
    assert r.status_code == 401


async def test_reviewer_can_hit_all_four_endpoints(
    seeded_reviewer, reviewer_token, auth_client
):
    """正常 reviewer 以有效 JWT 分别调四端点:均不 401/403(业务结果无所谓)。"""
    await _clean_projects()
    client = await auth_client(reviewer_token)

    # POST
    r = await client.post("/api/projects/", json={"name": "one"})
    assert r.status_code == 201
    pid = r.json()["id"]

    # GET list
    r = await client.get("/api/projects/")
    assert r.status_code == 200

    # GET detail
    r = await client.get(f"/api/projects/{pid}")
    assert r.status_code == 200

    # DELETE
    r = await client.delete(f"/api/projects/{pid}")
    assert r.status_code == 204


# -----------------------------------------------------------------------------
# Requirement 7: C4+ 占位字段 (2 scenarios)
# -----------------------------------------------------------------------------


async def test_detail_contains_placeholder_fields(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    p = await _seed_project(owner_id=seeded_reviewer.id, name="p")

    client = await auth_client(reviewer_token)
    r = await client.get(f"/api/projects/{p.id}")
    body = r.json()
    assert body["bidders"] == []
    assert body["files"] == []
    # C4 起 progress 由真实聚合产出;空项目所有计数 = 0
    assert body["progress"]["total_bidders"] == 0


async def test_list_items_contain_risk_level_field(
    seeded_reviewer, reviewer_token, auth_client
):
    await _clean_projects()
    await _seed_project(owner_id=seeded_reviewer.id, name="p1")
    await _seed_project(owner_id=seeded_reviewer.id, name="p2")

    client = await auth_client(reviewer_token)
    r = await client.get("/api/projects/")
    body = r.json()
    for item in body["items"]:
        assert "risk_level" in item
        assert item["risk_level"] is None
