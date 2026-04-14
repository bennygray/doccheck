"""Auth 相关 Pydantic schemas (C2 auth)。"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class UserPublic(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    must_change_password: bool

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


# 密码强度:≥8 位 + 至少一位字母 + 至少一位数字 (US-1.4 AC5)
_PWD_LETTER_RE = re.compile(r"[A-Za-z]")
_PWD_DIGIT_RE = re.compile(r"\d")


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _validate_strength(cls, v: str) -> str:
        if not _PWD_LETTER_RE.search(v):
            raise ValueError("密码必须包含至少一个字母")
        if not _PWD_DIGIT_RE.search(v):
            raise ValueError("密码必须包含至少一个数字")
        return v


class LockedResponse(BaseModel):
    """429 响应 body:告知剩余锁定时间。"""

    detail: str
    retry_after_seconds: int
