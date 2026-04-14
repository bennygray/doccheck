"""报价配置/规则路由 (C4 file-upload §5.2)。

prefix = ``/api/projects/{project_id}``。覆盖:
- GET / PUT /price-config         项目报价元配置(1:1)
- GET / PUT /price-rules          列映射规则骨架(C5 LLM 填,C4 端点骨架)

权限沿用 C3 项目可见性 helper。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.bidder import Bidder
from app.models.price_config import ProjectPriceConfig
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.schemas.price import (
    PriceParsingRuleRead,
    PriceParsingRuleWrite,
    ProjectPriceConfigRead,
    ProjectPriceConfigWrite,
)
from app.services.parser.pipeline.trigger import trigger_pipeline

router = APIRouter()

# 项目级 Lock:`PUT /price-rules/{id}` 并发修正时保序;重回填未完成前第二次 PUT 返 409
_PROJECT_RULE_UPDATE_LOCKS: dict[int, asyncio.Lock] = {}


def _project_rule_lock(project_id: int) -> asyncio.Lock:
    lock = _PROJECT_RULE_UPDATE_LOCKS.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        _PROJECT_RULE_UPDATE_LOCKS[project_id] = lock
    return lock


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


# ----------------------------------------------- C5: PUT /{id} with 重回填

@router.put(
    "/{project_id}/price-rules/{rule_id}",
    response_model=PriceParsingRuleRead,
)
async def put_price_rule_with_refill(
    project_id: int,
    rule_id: int,
    body: PriceParsingRuleWrite,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PriceParsingRuleRead:
    """修改列映射 → DELETE 项目所有 price_items → 重新触发所有 bidder 的报价回填。

    - 项目级 asyncio.Lock 保护并发;第二次并发 PUT 返 409
    - created_by_llm 强制置 False(标记人工修正)
    - bidder 退回 identified 状态 → pipeline 重跑 pricing 阶段
    """
    await _fetch_visible_project(session, user, project_id)
    lock = _project_rule_lock(project_id)
    if lock.locked():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "修正正在进行中,请稍后重试"
        )

    async with lock:
        rule = await session.get(PriceParsingRule, rule_id)
        if rule is None or rule.project_id != project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")

        rule.sheet_name = body.sheet_name
        rule.header_row = body.header_row
        rule.column_mapping = body.column_mapping
        rule.created_by_llm = False  # 人工修正标记
        rule.confirmed = True
        rule.status = "confirmed"

        # 清该项目所有 price_items
        await session.execute(
            delete(PriceItem).where(
                PriceItem.bidder_id.in_(
                    select(Bidder.id).where(Bidder.project_id == project_id)
                )
            )
        )

        # 所有 priced/price_partial/price_failed 的 bidder 退回 identified,让 pipeline 重跑报价阶段
        bidders_to_retrigger = (
            await session.execute(
                select(Bidder).where(
                    Bidder.project_id == project_id,
                    Bidder.deleted_at.is_(None),
                    Bidder.parse_status.in_(
                        ["priced", "price_partial", "price_failed"]
                    ),
                )
            )
        ).scalars().all()
        for b in bidders_to_retrigger:
            b.parse_status = "identified"
            b.parse_error = None

        await session.commit()
        await session.refresh(rule)

        # 触发重跑(Lock 持有中;后续 pipeline 协程独立)
        for b in bidders_to_retrigger:
            await trigger_pipeline(b.id)

    return PriceParsingRuleRead.model_validate(rule)


__all__ = ["router"]
