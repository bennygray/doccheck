"""BidDocument Pydantic schemas (C4 file-upload §6.2)。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class BidDocumentResponse(BaseModel):
    """``GET /bidders/{bid}/documents`` 单条响应。"""

    id: int
    bidder_id: int
    file_name: str
    file_path: str
    file_size: int
    file_type: str
    md5: str
    file_role: str | None  # C5 LLM 填,C4 阶段恒 null
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

    model_config = {"from_attributes": True}


class UploadResult(BaseModel):
    """``POST /bidders/{bid}/upload`` 与 ``POST /bidders``(带 file)的返回体。

    new_files: 新插入的归档行 ID 列表;前端可据此乐观更新文件树骨架。
    skipped_duplicates: 因 MD5 已存在被跳过的 archive MD5 列表(D8 决策,粒度
    = 同 bidder 内)。
    """

    bidder_id: int
    archive_filename: str | None = None
    new_files: list[int] = []
    skipped_duplicates: list[str] = []


class ProjectProgress(BaseModel):
    """ProjectDetailResponse.progress 字段类型(MODIFIED Requirement)。"""

    total_bidders: int
    pending_count: int
    extracting_count: int
    extracted_count: int
    failed_count: int
    needs_password_count: int


__all__ = [
    "BidDocumentResponse",
    "BidDocumentSummary",
    "ProjectProgress",
    "UploadResult",
]
