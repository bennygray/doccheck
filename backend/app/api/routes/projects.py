"""项目管理路由 (C3 project-mgmt)

端点(均挂 ``Depends(get_current_user)``):
- POST   /api/projects/       创建项目 → 201
- GET    /api/projects/       列表(分页/筛选/搜索),reviewer 仅见自己
- GET    /api/projects/{id}   详情,reviewer 访问他人 → 404(防存在性泄露)
- DELETE /api/projects/{id}   软删除;status=analyzing → 409;已软删 → 404

对齐 openspec/changes/project-mgmt/specs/project-mgmt/spec.md 的 7 个 Requirement。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.schemas.bid_document import (
    BidDocumentSummary,
    ProjectProgress,
)
from app.schemas.bidder import BidderSummary
from app.schemas.project import (
    ProjectCreate,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectResponse,
)

router = APIRouter()

# 合法 status / risk_level 白名单(与 schema 保持一致;路由层再过一次防越过 422)
_ALLOWED_STATUSES = frozenset(
    {"draft", "parsing", "ready", "analyzing", "completed"}
)
_ALLOWED_RISK_LEVELS = frozenset({"high", "medium", "low"})


@router.post(
    "/",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    body: ProjectCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectResponse:
    project = Project(
        name=body.name,
        bid_code=body.bid_code,
        max_price=body.max_price,
        description=body.description,
        status="draft",
        owner_id=user.id,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return ProjectResponse.model_validate(project)


@router.get("/", response_model=ProjectListResponse)
async def list_projects(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=12, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    risk_level: str | None = Query(default=None),
    search: str | None = Query(default=None),
) -> ProjectListResponse:
    # 白名单校验(越界返 422)
    if status_filter is not None and status_filter not in _ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"非法 status: {status_filter}",
        )
    if risk_level is not None and risk_level not in _ALLOWED_RISK_LEVELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"非法 risk_level: {risk_level}",
        )

    # 统一走 helper:自动带软删过滤 + 角色过滤
    base_stmt = get_visible_projects_stmt(user)

    if status_filter:
        base_stmt = base_stmt.where(Project.status == status_filter)
    if risk_level:
        base_stmt = base_stmt.where(Project.risk_level == risk_level)
    if search:
        kw = f"%{search.strip()}%"
        base_stmt = base_stmt.where(
            or_(Project.name.ilike(kw), Project.bid_code.ilike(kw))
        )

    # 计数(注意:count 要基于同一过滤条件的 subquery,避免误算 JOIN 结果)
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    # 分页 + 默认排序
    offset = (page - 1) * size
    page_stmt = (
        base_stmt.order_by(Project.created_at.desc()).offset(offset).limit(size)
    )
    rows = (await session.execute(page_stmt)).scalars().all()

    return ProjectListResponse(
        items=[ProjectResponse.model_validate(p) for p in rows],
        total=total,
        page=page,
        size=size,
    )


async def _fetch_visible_project(
    session: AsyncSession, user: User, project_id: int
) -> Project:
    """统一的"可见项目"取行 helper,未命中统一 404(不区分"不存在 / 无权 / 已软删")。"""
    stmt = get_visible_projects_stmt(user).where(Project.id == project_id)
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在",
        )
    return project


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProjectDetailResponse:
    project = await _fetch_visible_project(session, user, project_id)

    # C4: 真实聚合 bidders / files / progress(file-upload spec MODIFIED Req)
    bidders_rows = (
        await session.execute(
            select(Bidder)
            .where(Bidder.project_id == project_id, Bidder.deleted_at.is_(None))
            .order_by(Bidder.created_at.desc())
        )
    ).scalars().all()

    if bidders_rows:
        bidder_ids = [b.id for b in bidders_rows]
        files_rows = (
            await session.execute(
                select(BidDocument)
                .where(BidDocument.bidder_id.in_(bidder_ids))
                .order_by(BidDocument.created_at.asc())
            )
        ).scalars().all()
    else:
        files_rows = []

    progress = ProjectProgress(
        total_bidders=len(bidders_rows),
        pending_count=sum(1 for b in bidders_rows if b.parse_status == "pending"),
        extracting_count=sum(1 for b in bidders_rows if b.parse_status == "extracting"),
        extracted_count=sum(
            1 for b in bidders_rows if b.parse_status in {"extracted", "partial"}
        ),
        failed_count=sum(1 for b in bidders_rows if b.parse_status == "failed"),
        needs_password_count=sum(
            1 for b in bidders_rows if b.parse_status == "needs_password"
        ),
    )

    detail = ProjectDetailResponse.model_validate(project)
    detail.bidders = [BidderSummary.model_validate(b) for b in bidders_rows]
    detail.files = [BidDocumentSummary.model_validate(f) for f in files_rows]
    detail.progress = progress
    return detail


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    project = await _fetch_visible_project(session, user, project_id)

    if project.status == "analyzing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="检测进行中,无法删除",
        )

    project.deleted_at = datetime.now(timezone.utc)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
