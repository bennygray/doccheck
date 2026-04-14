"""C5 报价项查询路由。

prefix = ``/api/projects/{project_id}``。端点:
- GET /bidders/{bidder_id}/price-items → 该 bidder 的 price_items 列表

权限沿用 C3 项目可见性;未到 priced 阶段返空数组。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.bidder import Bidder
from app.models.price_item import PriceItem
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.schemas.price_item import PriceItemResponse

router = APIRouter()


async def _fetch_visible_bidder(
    session: AsyncSession,
    user: User,
    project_id: int,
    bidder_id: int,
) -> Bidder:
    visible = get_visible_projects_stmt(user).subquery()
    stmt = (
        select(Bidder)
        .join(visible, Bidder.project_id == visible.c.id)
        .where(
            Bidder.id == bidder_id,
            Bidder.project_id == project_id,
            Bidder.deleted_at.is_(None),
        )
    )
    bidder = (await session.execute(stmt)).scalar_one_or_none()
    if bidder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "投标人不存在")
    return bidder


@router.get(
    "/{project_id}/bidders/{bidder_id}/price-items",
    response_model=list[PriceItemResponse],
)
async def list_price_items(
    project_id: int,
    bidder_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PriceItemResponse]:
    await _fetch_visible_bidder(session, user, project_id, bidder_id)
    rows = (
        await session.execute(
            select(PriceItem)
            .where(PriceItem.bidder_id == bidder_id)
            .order_by(PriceItem.sheet_name.asc(), PriceItem.row_index.asc())
        )
    ).scalars().all()
    return [PriceItemResponse.model_validate(r) for r in rows]


__all__ = ["router"]
