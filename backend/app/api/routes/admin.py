"""Admin 管理路由 (C17 admin-users)

用户管理: GET/POST/PATCH /api/admin/users
规则配置: GET/PUT /api/admin/rules
全部 require_role("admin") 守护。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.db.session import get_db
from app.models.system_config import SystemConfig
from app.models.user import User
from app.schemas.admin import (
    CreateUserRequest,
    LLMConfigResponse,
    LLMConfigUpdate,
    LLMTestRequest,
    LLMTestResponse,
    RulesConfigRequest,
    RulesConfigResponse,
    UpdateUserRequest,
    UserPublicAdmin,
)
from app.services.admin.llm_reader import (
    mask_api_key,
    read_llm_config,
    write_llm_config,
)
from app.services.admin.rules_defaults import DEFAULT_RULES_CONFIG
from app.services.admin.rules_reader import get_active_rules
from app.services.auth.password import hash_password
from app.services.llm.tester import test_connection

router = APIRouter()

_admin = require_role("admin")


# ── 用户管理 ──


@router.get("/users", response_model=list[UserPublicAdmin])
async def list_users(
    session: AsyncSession = Depends(get_db),
    _current: User = Depends(_admin),
) -> list[User]:
    result = await session.execute(select(User).order_by(User.id))
    return list(result.scalars().all())


@router.post(
    "/users",
    response_model=UserPublicAdmin,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    body: CreateUserRequest,
    session: AsyncSession = Depends(get_db),
    _current: User = Depends(_admin),
) -> User:
    # 用户名唯一检查
    existing = await session.execute(
        select(User).where(User.username == body.username)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        )

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=True,
        must_change_password=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserPublicAdmin)
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(_admin),
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # admin 不能禁用自己
    if body.is_active is False and user.id == current.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能禁用自己",
        )

    if body.is_active is not None:
        user.is_active = body.is_active
    if body.role is not None:
        user.role = body.role

    await session.commit()
    await session.refresh(user)
    return user


# ── 规则配置 ──


@router.get("/rules", response_model=RulesConfigResponse)
async def get_rules(
    session: AsyncSession = Depends(get_db),
    _current: User = Depends(_admin),
) -> dict:
    config = await get_active_rules(session)
    # 尝试读取 updated_by / updated_at
    row = (
        await session.execute(select(SystemConfig).where(SystemConfig.id == 1))
    ).scalar_one_or_none()
    return {
        "config": config,
        "updated_by": row.updated_by if row else None,
        "updated_at": row.updated_at if row else None,
    }


@router.put("/rules", response_model=RulesConfigResponse)
async def update_rules(
    body: RulesConfigRequest,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(_admin),
) -> dict:
    row = (
        await session.execute(select(SystemConfig).where(SystemConfig.id == 1))
    ).scalar_one_or_none()

    if body.restore_defaults:
        new_config = DEFAULT_RULES_CONFIG
    else:
        new_config = body.to_config_dict()

    if row is None:
        row = SystemConfig(id=1, config=new_config, updated_by=current.id)
        session.add(row)
    else:
        row.config = new_config
        row.updated_by = current.id

    await session.commit()
    await session.refresh(row)
    return {
        "config": row.config,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }


# ── LLM 配置(admin-llm-config) ──


@router.get("/llm", response_model=LLMConfigResponse)
async def get_llm_config(
    session: AsyncSession = Depends(get_db),
    _current: User = Depends(_admin),
) -> LLMConfigResponse:
    cfg = await read_llm_config(session)
    return LLMConfigResponse(
        provider=cfg.provider,
        api_key_masked=mask_api_key(cfg.api_key),
        model=cfg.model,
        base_url=cfg.base_url,
        timeout_s=cfg.timeout_s,
        source=cfg.source,
    )


@router.put("/llm", response_model=LLMConfigResponse)
async def update_llm_config(
    body: LLMConfigUpdate,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(_admin),
) -> LLMConfigResponse:
    payload: dict[str, object] = {
        "provider": body.provider,
        "model": body.model,
        "base_url": body.base_url,
        "timeout_s": body.timeout_s,
    }
    if body.api_key:
        payload["api_key"] = body.api_key
    cfg = await write_llm_config(session, payload, actor_id=current.id)
    await session.commit()
    return LLMConfigResponse(
        provider=cfg.provider,
        api_key_masked=mask_api_key(cfg.api_key),
        model=cfg.model,
        base_url=cfg.base_url,
        timeout_s=cfg.timeout_s,
        source=cfg.source,
    )


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm_connection(
    body: LLMTestRequest,
    session: AsyncSession = Depends(get_db),
    _current: User = Depends(_admin),
) -> LLMTestResponse:
    # 字段缺省用 DB 当前配置兜底
    current = await read_llm_config(session)
    provider = body.provider or current.provider
    # api_key:显式传入优先;空字符串视为"用当前 DB key"(便于不重新输入就测试)
    api_key = body.api_key if body.api_key else current.api_key
    model = body.model or current.model
    base_url = body.base_url if body.base_url is not None else current.base_url
    timeout_s = body.timeout_s if body.timeout_s is not None else min(current.timeout_s, 10)

    ok, latency_ms, error = await test_connection(
        provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_s=timeout_s,
    )
    return LLMTestResponse(ok=ok, latency_ms=latency_ms, error=error)
