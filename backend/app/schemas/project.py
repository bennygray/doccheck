"""Project 相关 Pydantic schemas (C3 project-mgmt)。

对外契约,覆盖 spec.md 的"创建项目 / 项目列表 / 项目详情 / 为 C4+ 预留的占位字段"
四个 Requirement 的入参与返回格式。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.schemas.bid_document import BidDocumentSummary, ProjectProgress
from app.schemas.bidder import BidderSummary


# 合法的 status 取值集合;C3 阶段 API 只会产生 "draft",其余值预留给 C6+
_ALLOWED_STATUSES = frozenset(
    {"draft", "parsing", "ready", "analyzing", "completed"}
)
_ALLOWED_RISK_LEVELS = frozenset({"high", "medium", "low"})


class ProjectCreate(BaseModel):
    """``POST /api/projects/`` 请求体。

    字段约束对齐 US-2.1 AC 与 spec.md "创建项目" Requirement 的 Scenario:
    - ``name`` 必填、非空、≤100 字符
    - ``bid_code`` 选填、≤50 字符
    - ``max_price`` 选填、非负、最多两位小数(DECIMAL(18,2))
    - ``description`` 选填、≤500 字符
    """

    name: str = Field(..., min_length=1, max_length=100)
    bid_code: str | None = Field(default=None, max_length=50)
    max_price: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=2
    )
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _strip_and_require_nonblank(cls, v: str) -> str:
        # 前端可能提交纯空白,逻辑上也视为空
        stripped = v.strip()
        if not stripped:
            raise ValueError("name 不能为空")
        return stripped

    @field_validator("bid_code", "description")
    @classmethod
    def _empty_to_none(cls, v: str | None) -> str | None:
        # 前端 input 清空时 value 为 "",统一归一化为 None 存库
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None


class ProjectResponse(BaseModel):
    """项目基础响应(列表与创建都用这个)。"""

    id: int
    name: str
    bid_code: str | None
    max_price: Decimal | None
    description: str | None
    status: str
    risk_level: str | None
    owner_id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    model_config = {"from_attributes": True}


class ProjectDetailResponse(ProjectResponse):
    """项目详情响应。

    C4 起 bidders / files / progress 由 ``GET /api/projects/{id}`` 路由真实
    JOIN 聚合(file-upload spec MODIFIED Requirement)。空项目返空数组与零进度。
    """

    bidders: list[BidderSummary] = Field(default_factory=list)
    files: list[BidDocumentSummary] = Field(default_factory=list)
    progress: ProjectProgress | None = None


class ProjectListResponse(BaseModel):
    """``GET /api/projects/`` 返回的分页容器。"""

    items: list[ProjectResponse]
    total: int
    page: int
    size: int


class ProjectListQuery(BaseModel):
    """列表查询参数(仅用于类型注释 / 内部校验,不直接作为端点参数)。"""

    page: int = Field(default=1, ge=1)
    size: int = Field(default=12, ge=1, le=100)
    status: str | None = None
    risk_level: str | None = None
    search: str | None = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if v not in _ALLOWED_STATUSES:
            raise ValueError(f"非法 status: {v}")
        return v

    @field_validator("risk_level")
    @classmethod
    def _validate_risk_level(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if v not in _ALLOWED_RISK_LEVELS:
            raise ValueError(f"非法 risk_level: {v}")
        return v

    @field_validator("search")
    @classmethod
    def _normalize_search(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None
