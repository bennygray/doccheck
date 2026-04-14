"""C4 L2 测试共享 helper - 项目/投标人/归档行 seed + token 制造。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.project import Project
from app.models.user import User
from app.services.auth.jwt import create_access_token
from app.services.auth.password import hash_password


def token_for(user: User) -> str:
    return create_access_token(
        user_id=user.id,
        role=user.role,
        pwd_v=int(user.password_changed_at.timestamp() * 1000),
        username=user.username,
    )


async def seed_user(username: str, role: str = "reviewer") -> User:
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


async def seed_project(
    *, owner_id: int, name: str, status_: str = "draft"
) -> Project:
    async with async_session() as s:
        p = Project(
            name=name,
            owner_id=owner_id,
            status=status_,
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p


async def seed_bidder(
    *, project_id: int, name: str = "A 公司", parse_status: str = "pending"
) -> Bidder:
    async with async_session() as s:
        b = Bidder(
            project_id=project_id,
            name=name,
            parse_status=parse_status,
        )
        s.add(b)
        await s.commit()
        await s.refresh(b)
        return b


async def seed_archive_doc(
    *,
    bidder_id: int,
    archive_path: Path,
    md5: str,
    file_name: str | None = None,
    file_type: str = ".zip",
    parse_status: str = "pending",
) -> BidDocument:
    async with async_session() as s:
        d = BidDocument(
            bidder_id=bidder_id,
            file_name=file_name or archive_path.name,
            file_path=str(archive_path),
            file_size=archive_path.stat().st_size if archive_path.exists() else 0,
            file_type=file_type,
            md5=md5,
            parse_status=parse_status,
            source_archive=file_name or archive_path.name,
        )
        s.add(d)
        await s.commit()
        await s.refresh(d)
        return d


async def soft_delete_bidder(bidder_id: int) -> None:
    """直接 SQL 软删,避免再调路由触发 extract 副作用。"""
    async with async_session() as s:
        b = await s.get(Bidder, bidder_id)
        if b is not None:
            b.deleted_at = datetime.now(timezone.utc)
        await s.commit()
