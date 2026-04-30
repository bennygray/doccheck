"""文档级操作路由 (C4 file-upload §5.1)。

prefix = ``/api/documents``。覆盖单条文档的:
- DELETE        硬删 ``bid_documents`` 记录(物理压缩包保留)
- GET /download 下载原始压缩包(US-3.3 AC-6:证据保全用)
- POST /decrypt 加密包密码重试(D2,无次数冻结)

文件 list 端点在 ``bidders.py`` 内(共享 ``/api/projects/{pid}/bidders/{bid}/documents`` 前缀)。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_image import DocumentImage
from app.models.document_metadata import DocumentMetadata
from app.models.document_text import DocumentText
from app.models.price_item import PriceItem
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.schemas.bid_document import (
    DocumentRolePatchRequest,
    DocumentRolePatchResponse,
)
from app.services.extract import trigger_extract
from app.services.parser.pipeline.trigger import trigger_pipeline

router = APIRouter()


async def _fetch_owned_document(
    session: AsyncSession, user: User, document_id: int
) -> tuple[BidDocument, Bidder, Project]:
    """JOIN 查文档 + 投标人 + 项目;权限按项目可见性,未命中 404。"""
    visible_projects = get_visible_projects_stmt(user).subquery()
    stmt = (
        select(BidDocument, Bidder, Project)
        .join(Bidder, BidDocument.bidder_id == Bidder.id)
        .join(Project, Bidder.project_id == Project.id)
        .join(visible_projects, Project.id == visible_projects.c.id)
        .where(
            BidDocument.id == document_id,
            Bidder.deleted_at.is_(None),
        )
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    return row[0], row[1], row[2]


# --------------------------------------------------------- DELETE /{id}

@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    doc, _bidder, _project = await _fetch_owned_document(session, user, document_id)
    await session.delete(doc)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------- GET /{id}/download

@router.get("/{document_id}/download")
async def download_document(
    document_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """下载原始压缩包。物理文件丢失返 410(US-3.3 AC-6 + spec scenario)。"""
    doc, _bidder, _project = await _fetch_owned_document(session, user, document_id)
    path = Path(doc.file_path)
    if not path.exists():
        raise HTTPException(status.HTTP_410_GONE, "原始文件已清理")

    mime, _ = mimetypes.guess_type(doc.file_name)
    return FileResponse(
        path=path,
        media_type=mime or "application/octet-stream",
        filename=doc.file_name,
    )


# ------------------------------------------------------- POST /{id}/decrypt

@router.post("/{document_id}/decrypt", status_code=status.HTTP_202_ACCEPTED)
async def decrypt_document(
    document_id: int,
    password: str = Body(..., embed=True, min_length=1),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """对加密压缩包重试解压(D2 — 不计数,不冻结)。"""
    doc, bidder, _project = await _fetch_owned_document(session, user, document_id)
    if doc.parse_status != "needs_password":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "当前状态不需要密码"
        )

    # 重置归档行 + bidder 状态,trigger_extract 会按 needs_password 选行
    doc.parse_status = "needs_password"  # 保持,extract 内部按 password 重处理
    bidder.parse_status = "extracting"
    bidder.parse_error = None
    await session.commit()

    await trigger_extract(bidder_id=bidder.id, password=password)
    return {"detail": "已触发重新解压"}


# ------------------------------------------------ PATCH /{id}/role  (C5 US-4.3)

_COMPLETED_WARN = "文档角色已修改,当前报告基于修改前分类,建议重新检测"


@router.patch("/{document_id}/role")
async def patch_document_role(
    document_id: int,
    body: DocumentRolePatchRequest,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentRolePatchResponse:
    """修改文档角色;不触发 re-parse,不改变项目 status。

    项目 status='completed' → 响应附 warn 字段(前端据此显示 banner)。
    """
    doc, _bidder, project = await _fetch_owned_document(session, user, document_id)
    doc.file_role = body.role
    doc.role_confidence = "user"
    await session.commit()

    warn = _COMPLETED_WARN if project.status == "completed" else None
    return DocumentRolePatchResponse(
        id=doc.id,
        file_role=doc.file_role,
        role_confidence=doc.role_confidence,
        warn=warn,
    )


# -------------------------------------------- POST /{id}/re-parse  (C5 US-4.2)

@router.post("/{document_id}/re-parse", status_code=status.HTTP_202_ACCEPTED)
async def re_parse_document(
    document_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """重置单文档的 pipeline。

    - DELETE document_texts/metadata/images 记录
    - 若 file_role='pricing':DELETE 该 bidder 所有 price_items + bidder 退回 identified
    - bid_document.parse_status 置 identifying + trigger pipeline
    """
    doc, bidder, _project = await _fetch_owned_document(session, user, document_id)

    # 清提取侧表
    await session.execute(
        delete(DocumentText).where(DocumentText.bid_document_id == doc.id)
    )
    await session.execute(
        delete(DocumentMetadata).where(
            DocumentMetadata.bid_document_id == doc.id
        )
    )
    await session.execute(
        delete(DocumentImage).where(DocumentImage.bid_document_id == doc.id)
    )

    # pricing 文档:清 bidder 报价项 + 状态回退
    if doc.file_role == "pricing":
        await session.execute(
            delete(PriceItem).where(PriceItem.bidder_id == bidder.id)
        )
        if bidder.parse_status in ("priced", "price_partial", "price_failed"):
            bidder.parse_status = "identified"

    # 文档本身回到可重跑状态
    doc.parse_status = "extracted"  # 让 pipeline 重走 identify 阶段
    doc.parse_error = None
    doc.file_role = None
    doc.role_confidence = None
    await session.commit()

    await trigger_pipeline(bidder.id)
    return {"detail": "已触发重新解析"}


__all__ = ["router"]
