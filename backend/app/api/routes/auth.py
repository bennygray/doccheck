"""Auth 路由 (C2 auth)

端点:
- POST /api/auth/login         → 200 + JWT | 401 | 403 | 429
- POST /api/auth/logout        → 204(前端清 token 即可,后端仅返确认)
- GET  /api/auth/me            → 200 (Depends get_current_user)
- POST /api/auth/change-password → 200 | 400 | 422
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    UserPublic,
)
from app.services.auth.jwt import create_access_token
from app.services.auth.lockout import check_locked, record_failure, reset_failure
from app.services.auth.password import hash_password, verify_password

router = APIRouter()


def _generic_401() -> HTTPException:
    """登录阶段通用错误(防枚举):用户名不存在 / 密码错 都返相同。"""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="用户名或密码错误",
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> LoginResponse:
    # 先按 username 查用户,用 with_for_update 避免并发 fail 丢更新 (design.md D4)
    stmt = select(User).where(User.username == body.username).with_for_update()
    user = (await session.execute(stmt)).scalar_one_or_none()

    if user is None:
        # 用户名不存在 → 通用 401,不写 DB(防用户名枚举型 DoS)
        raise _generic_401()

    # 1. 锁定检查(即便密码正确也拒绝,安全优先)
    remaining = check_locked(user)
    if remaining is not None:
        retry = max(1, math.ceil(remaining.total_seconds()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "detail": "账户已锁定,请稍后再试",
                "retry_after_seconds": retry,
            },
            headers={"Retry-After": str(retry)},
        )

    # 2. 禁用检查(在密码校验之前,避免暴力破解禁用账户也要花 bcrypt 时间)
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用",
        )

    # 3. 密码校验
    if not verify_password(body.password, user.password_hash):
        record_failure(user)
        await session.commit()
        raise _generic_401()

    # 4. 成功 → 清零计数
    reset_failure(user)
    await session.commit()
    await session.refresh(user)

    token = create_access_token(
        user_id=user.id,
        role=user.role,
        pwd_v=int(user.password_changed_at.timestamp() * 1000),
        username=user.username,
    )
    return LoginResponse(access_token=token, user=UserPublic.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> Response:
    """登出端点 — 前端清 token 即可,后端无状态。

    保留端点便于前端显式调用(日志/审计可 in future),当前仅返 204。
    """
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserPublic)
async def me(user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(user)


@router.post("/change-password", response_model=UserPublic)
async def change_password(
    body: ChangePasswordRequest,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserPublic:
    # 必须重新加载为可写(get_current_user 返回的已脱离 session 的只读态不够)
    stmt = select(User).where(User.id == user.id).with_for_update()
    live = (await session.execute(stmt)).scalar_one()

    if not verify_password(body.old_password, live.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="原密码错误",
        )

    live.password_hash = hash_password(body.new_password)
    live.must_change_password = False
    live.password_changed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(live)

    return UserPublic.model_validate(live)
