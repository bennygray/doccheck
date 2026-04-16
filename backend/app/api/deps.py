"""FastAPI 依赖 (C2 auth):

- get_current_user:解析 Authorization: Bearer JWT → 查 DB → 校验 pwd_v 与 password_changed_at 一致性
- require_role(role):基于 get_current_user 再校角色;角色不符 403,is_active=false 也 403

返回码约定 (design.md D11):
- 无 token / 过期 / 签名错 / pwd_v 不符 → 401
- 角色不足 / is_active=false → 403
- 锁定中由 auth 路由返 429(不在本依赖中处理)
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.services.auth.jwt import TokenInvalid, decode_access_token


async def get_current_user(
    authorization: str | None = Header(default=None),
    access_token: str | None = Query(default=None, include_in_schema=False),
    session: AsyncSession = Depends(get_db),
) -> User:
    # 优先从 Header 读 Bearer token；回退到 query param access_token（SSE EventSource 场景）
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif access_token:
        token = access_token

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(token)
    except TokenInvalid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # pwd_v 校验:JWT 中的 pwd_v 必须与 DB 当前 password_changed_at 一致
    # 不一致说明改密后旧 token 应失效
    # 注:使用毫秒精度,避免"同一秒内连续改密"导致 pwd_v 碰撞
    expected_pwd_v = int(user.password_changed_at.timestamp() * 1000)
    token_pwd_v = payload.get("pwd_v")
    if token_pwd_v != expected_pwd_v:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_role(role: str):
    """依赖工厂:返回一个 FastAPI 依赖,校验 current_user 角色与 is_active。

    - user.is_active=false → 403
    - user.role != role → 403
    """

    async def _checker(user: User = Depends(get_current_user)) -> User:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="账户已被禁用",
            )
        if user.role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足",
            )
        return user

    return _checker
