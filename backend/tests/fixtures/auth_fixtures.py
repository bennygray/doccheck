"""Auth 测试共享 fixture (C2)。

- `seeded_admin` / `seeded_reviewer`:插 DB 并返回 User ORM 对象
- `admin_token` / `reviewer_token`:对应的有效 JWT
- `auth_client` factory:返回已挂 Authorization 头的 httpx.AsyncClient

注意:每个测试会清理 users 表后重新插入 seed 用户,避免测试间污染;
admin alembic seed 在迁移时已创建,这里的 fixture 做重置保证状态一致。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Callable

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db.session import async_session
from app.main import app
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.async_task import AsyncTask
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.price_config import ProjectPriceConfig
from app.models.document_image import DocumentImage
from app.models.document_metadata import DocumentMetadata
from app.models.document_sheet import DocumentSheet
from app.models.document_text import DocumentText
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project
from app.models.system_config import SystemConfig
from app.models.user import User
from app.services.auth.jwt import create_access_token
from app.services.auth.password import hash_password


async def _delete_all() -> None:
    """按 FK 依赖顺序清所有业务表。

    顺序: bid_documents → bidders → price_parsing_rules → project_price_configs
            → projects → users。新表加进来必须按 FK 顺序往前插入。
    """
    async with async_session() as s:
        # C6: async_tasks 无 FK,先清无妨
        await s.execute(delete(AsyncTask))
        # C6: analysis 相关 4 张表依赖 projects / bidders,在 bidders 之前清
        await s.execute(delete(AnalysisReport))
        await s.execute(delete(OverallAnalysis))
        await s.execute(delete(PairComparison))
        await s.execute(delete(AgentTask))
        # C5: 先清 price_items + document_* 三张表(都引用 bid_documents)
        await s.execute(delete(PriceItem))
        await s.execute(delete(DocumentImage))
        await s.execute(delete(DocumentMetadata))
        await s.execute(delete(DocumentSheet))
        await s.execute(delete(DocumentText))
        await s.execute(delete(BidDocument))
        await s.execute(delete(Bidder))
        await s.execute(delete(PriceParsingRule))
        await s.execute(delete(ProjectPriceConfig))
        await s.execute(delete(Project))
        await s.execute(delete(SystemConfig))
        await s.execute(delete(User))
        await s.commit()


@pytest_asyncio.fixture
async def clean_users() -> AsyncIterator[None]:
    """每个用到 users 表的 L2 测试前后都清表,避免状态污染。

    FK 依赖:projects.owner_id → users.id;C4 后又叠了 bidders / bid_documents
    / price_configs / price_rules,清理顺序从子表向父表。所有 C2/C3/C4 测试
    共享同一 fixture,不必各自维护。
    """
    await _delete_all()
    yield
    await _delete_all()


@pytest_asyncio.fixture
async def seeded_admin(clean_users: None) -> User:
    """插一个 admin 用户(must_change_password=false,方便测试绕过强制改密)。"""
    async with async_session() as s:
        u = User(
            username="admin",
            password_hash=hash_password("admin123"),
            role="admin",
            is_active=True,
            must_change_password=False,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


@pytest_asyncio.fixture
async def seeded_reviewer(clean_users: None) -> User:
    async with async_session() as s:
        u = User(
            username="reviewer1",
            password_hash=hash_password("Review1234"),
            role="reviewer",
            is_active=True,
            must_change_password=False,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


def _token_for(user: User) -> str:
    return create_access_token(
        user_id=user.id,
        role=user.role,
        pwd_v=int(user.password_changed_at.timestamp() * 1000),
        username=user.username,
    )


@pytest_asyncio.fixture
async def admin_token(seeded_admin: User) -> str:
    return _token_for(seeded_admin)


@pytest_asyncio.fixture
async def reviewer_token(seeded_reviewer: User) -> str:
    return _token_for(seeded_reviewer)


@pytest_asyncio.fixture
async def auth_client() -> AsyncIterator[Callable[[str | None], AsyncClient]]:
    """工厂 fixture:调用 `await auth_client(token)` 得到一个 AsyncClient。

    传 None 得到未认证的 client。
    """
    clients: list[AsyncClient] = []

    async def _make(token: str | None = None) -> AsyncClient:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        c = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=headers,
        )
        clients.append(c)
        return c

    yield _make
    for c in clients:
        await c.aclose()
