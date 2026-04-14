"""Bidder Pydantic schemas (C4 file-upload §6.1)。

对应 spec.md "投标人 CRUD" Requirement 的 9 个 Scenario 入参与返回结构。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class BidderCreate(BaseModel):
    """``POST /api/projects/{pid}/bidders`` 表单字段(``name`` 部分);

    实际请求是 multipart,FastAPI 用 ``Form(...)`` 单字段接,这个 schema 主要给
    L1 单测做规则校验复用。
    """

    name: str = Field(..., min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def _strip_nonblank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("name 不能为空")
        return stripped


class BidderSummary(BaseModel):
    """ProjectDetailResponse.bidders 用的轻量摘要(MODIFIED Requirement)。"""

    id: int
    name: str
    parse_status: str
    file_count: int

    model_config = {"from_attributes": True}


class BidderResponse(BaseModel):
    """完整投标人响应,GET /bidders / GET /bidders/{bid} 用。"""

    id: int
    name: str
    project_id: int
    parse_status: str
    parse_error: str | None
    file_count: int
    identity_info: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BidderListResponse(BaseModel):
    """``GET /bidders`` 返回容器。当前不分页,直接平铺。"""

    items: list[BidderResponse]
    total: int


__all__ = [
    "BidderCreate",
    "BidderListResponse",
    "BidderResponse",
    "BidderSummary",
]
