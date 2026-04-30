"""TenderDocument Pydantic schemas (detect-tender-baseline)。

招标方下发的招标文件 API 序列化层,与 BidDocument schemas 平行。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TenderDocumentResponse(BaseModel):
    """``GET /api/projects/{pid}/tender`` 单条响应。"""

    id: int
    project_id: int
    file_name: str
    file_path: str
    file_size: int
    md5: str
    parse_status: str  # pending / parsing / extracted / failed
    parse_error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TenderUploadResult(BaseModel):
    """``POST /api/projects/{pid}/tender`` 返回体。"""

    tender_id: int
    file_name: str
    parse_status: str  # 通常 'pending',触发异步解析后转 'parsing'/'extracted'/'failed'


__all__ = [
    "TenderDocumentResponse",
    "TenderUploadResult",
]
