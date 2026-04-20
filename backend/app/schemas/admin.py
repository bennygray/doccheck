"""Admin 管理 Pydantic schemas (C17 admin-users)。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ── 用户管理 ──


_PWD_LETTER_RE = re.compile(r"[A-Za-z]")
_PWD_DIGIT_RE = re.compile(r"\d")
_VALID_ROLES = {"admin", "reviewer"}


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)
    role: str = Field(default="reviewer")

    @field_validator("password")
    @classmethod
    def _validate_password(cls, v: str) -> str:
        if not _PWD_LETTER_RE.search(v):
            raise ValueError("密码必须包含至少一个字母")
        if not _PWD_DIGIT_RE.search(v):
            raise ValueError("密码必须包含至少一个数字")
        return v

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in _VALID_ROLES:
            raise ValueError(f"角色必须为 {_VALID_ROLES} 之一")
        return v


class UpdateUserRequest(BaseModel):
    is_active: bool | None = None
    role: str | None = None

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_ROLES:
            raise ValueError(f"角色必须为 {_VALID_ROLES} 之一")
        return v


class UserPublicAdmin(BaseModel):
    """Admin 用户列表返回体（比 auth.UserPublic 多 created_at）。"""

    id: int
    username: str
    role: str
    is_active: bool
    must_change_password: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 规则配置 ──


class DimensionConfig(BaseModel):
    enabled: bool = True
    weight: float | None = None
    llm_enabled: bool | None = None
    # 各维度特有阈值以 extra="allow" 透传
    model_config = {"extra": "allow"}

    @field_validator("weight")
    @classmethod
    def _weight_non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("权重不能为负数")
        return v


class RiskLevels(BaseModel):
    high: int = Field(..., ge=1, le=100)
    medium: int = Field(..., ge=1, le=100)

    @model_validator(mode="after")
    def _check_order(self) -> "RiskLevels":
        if self.high <= self.medium:
            raise ValueError("高风险阈值必须大于中风险阈值")
        return self


class RulesConfigRequest(BaseModel):
    """PUT /api/admin/rules 入参。

    restore_defaults=true 时忽略其他字段，直接恢复默认。
    否则需要提供完整配置。
    """

    restore_defaults: bool = False

    dimensions: dict[str, DimensionConfig] | None = None
    risk_levels: RiskLevels | None = None
    doc_role_keywords: dict[str, list[str]] | None = None
    hardware_keywords: list[str] | None = None
    metadata_whitelist: list[str] | None = None
    min_paragraph_length: int | None = Field(default=None, ge=1)
    file_retention_days: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check_completeness(self) -> "RulesConfigRequest":
        if self.restore_defaults:
            return self
        # 非恢复默认时，必须提供完整配置
        if self.dimensions is None or self.risk_levels is None:
            raise ValueError("非恢复默认时必须提供 dimensions 和 risk_levels")
        return self

    def to_config_dict(self) -> dict[str, Any]:
        """转为可存入 SystemConfig.config 的 dict。"""
        data: dict[str, Any] = {}
        if self.dimensions is not None:
            data["dimensions"] = {
                k: v.model_dump(exclude_none=False) for k, v in self.dimensions.items()
            }
        if self.risk_levels is not None:
            data["risk_levels"] = self.risk_levels.model_dump()
        if self.doc_role_keywords is not None:
            data["doc_role_keywords"] = self.doc_role_keywords
        if self.hardware_keywords is not None:
            data["hardware_keywords"] = self.hardware_keywords
        if self.metadata_whitelist is not None:
            data["metadata_whitelist"] = self.metadata_whitelist
        if self.min_paragraph_length is not None:
            data["min_paragraph_length"] = self.min_paragraph_length
        if self.file_retention_days is not None:
            data["file_retention_days"] = self.file_retention_days
        return data


class RulesConfigResponse(BaseModel):
    config: dict[str, Any]
    updated_by: int | None = None
    updated_at: datetime | None = None


# ── LLM 配置(admin-llm-config) ──

_VALID_LLM_PROVIDERS = {"dashscope", "openai", "custom"}


class LLMConfigResponse(BaseModel):
    """读取 LLM 配置,api_key 脱敏。"""

    provider: str
    api_key_masked: str  # eg. "sk-****abc1";完全为空时 ""
    model: str
    base_url: str | None
    timeout_s: int
    # 配置来源:"db" / "env" / "default",用于前端提示
    source: str


class LLMConfigUpdate(BaseModel):
    """更新 LLM 配置;api_key 空字符串 or None 时保持旧值不变(Req-3 场景 2)。"""

    provider: str
    api_key: str | None = None
    model: str = Field(..., min_length=1, max_length=200)
    base_url: str | None = None
    timeout_s: int = Field(default=30, ge=1, le=300)

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, v: str) -> str:
        if v not in _VALID_LLM_PROVIDERS:
            raise ValueError(
                f"provider 必须是以下之一:{sorted(_VALID_LLM_PROVIDERS)}"
            )
        return v

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("base_url 必须以 http:// 或 https:// 开头")
        return v.rstrip("/")


class LLMTestRequest(BaseModel):
    """测试连接请求;字段缺省时用 DB 当前配置。"""

    provider: str | None = None
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    timeout_s: int | None = Field(default=None, ge=1, le=30)

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_LLM_PROVIDERS:
            raise ValueError(
                f"provider 必须是以下之一:{sorted(_VALID_LLM_PROVIDERS)}"
            )
        return v


class LLMTestResponse(BaseModel):
    ok: bool
    latency_ms: int
    error: str | None = None
