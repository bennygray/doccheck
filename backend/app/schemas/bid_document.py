"""BidDocument Pydantic schemas (C4 file-upload + C5 parser-pipeline)。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# C5: 9 种文档角色枚举
DocumentRole = Literal[
    "technical",
    "construction",
    "pricing",
    "unit_price",
    "bid_letter",
    "qualification",
    "company_intro",
    "authorization",
    "other",
]


class BidDocumentResponse(BaseModel):
    """``GET /bidders/{bid}/documents`` 单条响应。"""

    id: int
    bidder_id: int
    file_name: str
    file_path: str
    file_size: int
    file_type: str
    md5: str
    file_role: str | None  # C5 LLM 填
    role_confidence: str | None  # C5 新增:high / low / user / null
    parse_status: str
    parse_error: str | None
    source_archive: str
    created_at: datetime

    model_config = {"from_attributes": True}


class BidDocumentSummary(BaseModel):
    """ProjectDetailResponse.files 用的轻量摘要(MODIFIED Requirement)。"""

    id: int
    bidder_id: int
    file_name: str
    file_type: str
    parse_status: str
    file_role: str | None = None  # C5 扩展
    role_confidence: str | None = None  # C5 扩展

    model_config = {"from_attributes": True}


class UploadResult(BaseModel):
    """``POST /bidders/{bid}/upload`` 与 ``POST /bidders``(带 file)的返回体。"""

    bidder_id: int
    archive_filename: str | None = None
    new_files: list[int] = []
    skipped_duplicates: list[str] = []


class ProjectProgress(BaseModel):
    """ProjectDetailResponse.progress 字段类型(C5 扩展 11 字段)。"""

    total_bidders: int
    pending_count: int
    extracting_count: int
    extracted_count: int
    # C5 新增阶段计数
    identifying_count: int = 0
    identified_count: int = 0
    pricing_count: int = 0
    priced_count: int = 0
    partial_count: int = 0  # partial + price_partial 合计
    failed_count: int = 0  # failed + identify_failed + price_failed 合计
    needs_password_count: int = 0


class DocumentRolePatchRequest(BaseModel):
    """``PATCH /api/documents/{id}/role`` 请求体 (C5 US-4.3 AC-4~5)。"""

    role: DocumentRole


class DocumentRolePatchResponse(BaseModel):
    """``PATCH /api/documents/{id}/role`` 响应体。

    项目 status='completed' 时附 warn 提示(spec "修改文档角色")。
    """

    id: int
    file_role: str
    role_confidence: str
    warn: str | None = None


__all__ = [
    "BidDocumentResponse",
    "BidDocumentSummary",
    "DocumentRole",
    "DocumentRolePatchRequest",
    "DocumentRolePatchResponse",
    "ProjectProgress",
    "UploadResult",
]
