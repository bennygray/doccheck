"""JWT 编解码 — python-jose HS256 (C2 auth)

载荷(claims):
- sub: user_id (str,jose 要求 str)
- role: "admin" | "reviewer"
- pwd_v: int(password_changed_at.timestamp())  改密后立即失效依赖此字段
- username: 便于日志(非安全敏感)
- exp: 过期时间 (int epoch)
- iat: 签发时间 (int epoch)

所有解码异常(过期/签名错/格式错)统一包装为 TokenInvalid,调用方仅需 try 一个异常。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings


class TokenInvalid(Exception):
    """JWT 校验失败的统一异常(过期/签名错/格式错/缺字段)。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def create_access_token(
    *,
    user_id: int,
    role: str,
    pwd_v: int,
    username: str,
    expires_minutes: int | None = None,
) -> str:
    """签发 JWT access token。

    参数:
        pwd_v: 通常传 int(user.password_changed_at.timestamp())
        expires_minutes: None 时取 settings.access_token_expire_minutes
    """
    now = datetime.now(timezone.utc)
    exp_min = (
        expires_minutes
        if expires_minutes is not None
        else settings.access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "role": role,
        "pwd_v": pwd_v,
        "username": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=exp_min)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """解码并校验 JWT。任何失败都抛 TokenInvalid。"""
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise TokenInvalid(str(exc)) from exc

    # 必要字段完整性检查(防止手工构造畸形但合法签名的 token)
    for key in ("sub", "role", "pwd_v", "exp"):
        if key not in payload:
            raise TokenInvalid(f"missing claim: {key}")
    return payload
