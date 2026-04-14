"""报价配置/规则路由 (C4 file-upload §5.2)。

prefix = ``/api/projects/{project_id}``。覆盖:
- GET / PUT /price-config         项目报价元配置(1:1)
- GET / PUT /price-rules          列映射规则骨架(C5 LLM 填,C4 端点骨架)

权限沿用 C3 项目可见性 helper。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.price_config import ProjectPriceConfig
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.schemas.price import (
    PriceParsingRuleRead,
    PriceParsingRuleWrite,
    ProjectPriceConfigRead,
    ProjectPriceConfigWrite,
)

router = APIRouter()


async def _fetch_visible_project(
    session: AsyncSession, user: User, project_id: int
) -> Project:
    stmt = get_visible_projects_stmt(user).where(Project.id == project_id)
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    return project


# ----------------------------------------------------- price-config (1:1)

@router.get(
    "/{project_id}/price-config",
    response_model=ProjectPriceConfigRead | None,
)
async def get_price_config(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectPriceConfigRead | None:
    await _fetch_visible_project(session, user, project_id)
    cfg = await session.get(ProjectPriceConfig, project_id)
    if cfg is None:
        return None
    return ProjectPriceConfigRead.model_validate(cfg)


@router.put(
    "/{project_id}/price-config",
    response_model=ProjectPriceConfigRead,
)
async def put_price_config(
    project_id: int,
    body: ProjectPriceConfigWrite,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectPriceConfigRead:
    await _fetch_visible_project(session, user, project_id)
    cfg = await session.get(ProjectPriceConfig, project_id)
    if cfg is None:
        cfg = ProjectPriceConfig(
            project_id=project_id,
            currency=body.currency,
            tax_inclusive=body.tax_inclusive,
            unit_scale=body.unit_scale,
        )
        session.add(cfg)
    else:
        cfg.currency = body.currency
        cfg.tax_inclusive = body.tax_inclusive
        cfg.unit_scale = body.unit_scale
    await session.commit()
    await session.refresh(cfg)
    return ProjectPriceConfigRead.model_validate(cfg)


# --------------------------------------------- price-rules (1 项目 → 多 sheet)

@router.get(
    "/{project_id}/price-rules",
    response_model=list[PriceParsingRuleRead],
)
async def list_price_rules(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PriceParsingRuleRead]:
    await _fetch_visible_project(session, user, project_id)
    rows = (
        await session.execute(
            select(PriceParsingRule)
            .where(PriceParsingRule.project_id == project_id)
            .order_by(PriceParsingRule.id.asc())
        )
    ).scalars().all()
    return [PriceParsingRuleRead.model_validate(r) for r in rows]


@router.put(
    "/{project_id}/price-rules",
    response_model=PriceParsingRuleRead,
)
async def put_price_rule(
    project_id: int,
    body: PriceParsingRuleWrite,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PriceParsingRuleRead:
    """新建或更新一条规则。

    带 ``id`` 视为 update;无 ``id`` 视为 insert。``project_id`` 路径参数权威。
    """
    await _fetch_visible_project(session, user, project_id)
    rule: PriceParsingRule | None = None
    if body.id is not None:
        rule = await session.get(PriceParsingRule, body.id)
        if rule is None or rule.project_id != project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
        rule.sheet_name = body.sheet_name
        rule.header_row = body.header_row
        rule.column_mapping = body.column_mapping
        rule.created_by_llm = body.created_by_llm
        rule.confirmed = body.confirmed
    else:
        rule = PriceParsingRule(
            project_id=project_id,
            sheet_name=body.sheet_name,
            header_row=body.header_row,
            column_mapping=body.column_mapping,
            created_by_llm=body.created_by_llm,
            confirmed=body.confirmed,
        )
        session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return PriceParsingRuleRead.model_validate(rule)


__all__ = ["router"]
