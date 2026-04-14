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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.services.extract import trigger_extract

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

    await trigger_extract(bidder.id, password=password)
    return {"detail": "已触发重新解压"}


__all__ = ["router"]
