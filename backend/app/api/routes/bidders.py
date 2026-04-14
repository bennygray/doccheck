"""投标人路由 (C4 file-upload §4)。

prefix = ``/api/projects/{project_id}/bidders``,挂在 main.py。所有端点
``Depends(get_current_user)`` + 项目级权限过滤(复用 C3 helper)。

端点对齐 spec.md "投标人 CRUD" + "文件上传(创建+追加)" Requirement。
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder, get_visible_bidders_stmt
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.schemas.bid_document import BidDocumentResponse, UploadResult
from app.schemas.bidder import (
    BidderCreate,
    BidderListResponse,
    BidderResponse,
)
from app.services.extract import trigger_extract
from app.services.upload import (
    FileTooLarge,
    UnsupportedMediaType,
    save_archive,
    validate_archive_file,
)

# 路由挂在 ``/api/projects/{project_id}/bidders`` 前缀
router = APIRouter()


# --------------------------------------------------------------- 通用 helper

async def _fetch_visible_project(
    session: AsyncSession, user: User, project_id: int
) -> Project:
    """复用 C3 模式:未命中统一 404,不区分"不存在 / 无权 / 已软删"。"""
    stmt = get_visible_projects_stmt(user).where(Project.id == project_id)
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    return project


async def _fetch_visible_bidder(
    session: AsyncSession, user: User, project_id: int, bidder_id: int
) -> Bidder:
    stmt = get_visible_bidders_stmt(user, project_id=project_id).where(
        Bidder.id == bidder_id
    )
    bidder = (await session.execute(stmt)).scalar_one_or_none()
    if bidder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "投标人不存在")
    return bidder


async def _peek_head_and_size(upload_file: UploadFile) -> tuple[bytes, int]:
    """读 head + 获取总大小,SpooledTemporaryFile seek 回 0 供后续 save_archive 使用。

    SpooledTemporaryFile.seek(0, 2) 拿 size,seek(0) 回头;UploadFile 内部就是
    这种 file-like。
    """
    head = await upload_file.read(64)
    # SpooledTemporaryFile 是 sync .file 句柄
    upload_file.file.seek(0, 2)
    size = upload_file.file.tell()
    upload_file.file.seek(0)
    return head, size


async def _persist_archive(
    *,
    session: AsyncSession,
    bidder: Bidder,
    upload_file: UploadFile,
) -> tuple[BidDocument | None, str | None]:
    """处理一个上传的归档:校验 → 落盘 → 写 bid_documents 行(pending)。

    Returns:
        ``(bid_doc_row | None, dup_md5 | None)``:成功返第一个;MD5 已存在返第二个;
        其他校验失败抛 ``HTTPException``。
    """
    head, total_size = await _peek_head_and_size(upload_file)
    try:
        validate_archive_file(
            filename=upload_file.filename or "archive",
            head_bytes=head,
            total_size=total_size,
        )
    except UnsupportedMediaType as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    except FileTooLarge as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc

    final_path, md5_hex, total_bytes = await save_archive(
        bidder.project_id, bidder.id, upload_file
    )

    # 同 bidder 内 archive MD5 已存在 → 跳过
    existing = (
        await session.execute(
            select(BidDocument.id).where(
                BidDocument.bidder_id == bidder.id,
                BidDocument.md5 == md5_hex,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # 物理文件已落盘,清掉避免冗余
        try:
            final_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None, md5_hex

    archive_ext = "." + (upload_file.filename or "archive").rsplit(".", 1)[-1].lower()
    archive_row = BidDocument(
        bidder_id=bidder.id,
        file_name=upload_file.filename or final_path.name,
        file_path=str(final_path),
        file_size=total_bytes,
        file_type=archive_ext,
        md5=md5_hex,
        parse_status="pending",
        parse_error=None,
        source_archive=upload_file.filename or final_path.name,
    )
    session.add(archive_row)
    try:
        await session.flush()
    except IntegrityError:
        # 罕见:并发同 MD5 下注 → 视为重复
        await session.rollback()
        try:
            final_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None, md5_hex
    return archive_row, None


# ---------------------------------------------------------- POST / 创建投标人

@router.post(
    "/",
    response_model=BidderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_bidder(
    project_id: int,
    name: str = Form(...),
    file: UploadFile | None = File(default=None),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BidderResponse:
    """创建投标人(可选附 file,multipart)。"""
    project = await _fetch_visible_project(session, user, project_id)

    # name 规则校验复用 BidderCreate(strip + 非空 + ≤200)
    try:
        validated = BidderCreate(name=name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # 同项目活跃 name 唯一(partial unique index 兜底,但应用层先查给清晰错码)
    dup = (
        await session.execute(
            select(Bidder.id).where(
                Bidder.project_id == project_id,
                Bidder.name == validated.name,
                Bidder.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "同项目内已存在该投标人名")

    bidder = Bidder(
        name=validated.name,
        project_id=project.id,
        parse_status="pending",
    )
    session.add(bidder)
    try:
        await session.flush()  # 拿到 bidder.id 才能落盘
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "同项目内已存在该投标人名") from exc

    if file is not None and file.filename:
        archive_row, _dup = await _persist_archive(
            session=session, bidder=bidder, upload_file=file
        )
        await session.commit()
        if archive_row is not None:
            await trigger_extract(bidder.id)
    else:
        await session.commit()

    await session.refresh(bidder)
    return BidderResponse.model_validate(bidder)


# ----------------------------------------------------- POST /{bid}/upload 追加

@router.post(
    "/{bidder_id}/upload",
    response_model=UploadResult,
    status_code=status.HTTP_201_CREATED,
)
async def upload_to_bidder(
    project_id: int,
    bidder_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UploadResult:
    bidder = await _fetch_visible_bidder(session, user, project_id, bidder_id)

    archive_row, dup_md5 = await _persist_archive(
        session=session, bidder=bidder, upload_file=file
    )
    await session.commit()

    if archive_row is not None:
        await trigger_extract(bidder.id)
        return UploadResult(
            bidder_id=bidder.id,
            archive_filename=archive_row.file_name,
            new_files=[archive_row.id],
            skipped_duplicates=[],
        )
    return UploadResult(
        bidder_id=bidder.id,
        archive_filename=file.filename,
        new_files=[],
        skipped_duplicates=[dup_md5] if dup_md5 else [],
    )


# --------------------------------------------------------------- GET /

@router.get("/", response_model=BidderListResponse)
async def list_bidders(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BidderListResponse:
    await _fetch_visible_project(session, user, project_id)  # 权限护栏

    rows = (
        await session.execute(
            get_visible_bidders_stmt(user, project_id=project_id).order_by(
                Bidder.created_at.desc()
            )
        )
    ).scalars().all()
    return BidderListResponse(
        items=[BidderResponse.model_validate(b) for b in rows], total=len(rows)
    )


# --------------------------------------------------------- GET /{bid}

@router.get("/{bidder_id}", response_model=BidderResponse)
async def get_bidder(
    project_id: int,
    bidder_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BidderResponse:
    bidder = await _fetch_visible_bidder(session, user, project_id, bidder_id)
    return BidderResponse.model_validate(bidder)


# --------------------------------------------------------- DELETE /{bid}

@router.delete("/{bidder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bidder(
    project_id: int,
    bidder_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    project = await _fetch_visible_project(session, user, project_id)
    bidder = await _fetch_visible_bidder(session, user, project_id, bidder_id)

    if project.status == "analyzing":
        raise HTTPException(status.HTTP_409_CONFLICT, "检测进行中,无法删除投标人")

    # 1. 硬删 bid_documents(D1:文件依附 bidder 生命周期)
    await session.execute(
        BidDocument.__table__.delete().where(BidDocument.bidder_id == bidder.id)
    )
    # 2. 软删 bidder
    bidder.deleted_at = datetime.now(timezone.utc)
    await session.commit()

    # 3. rmtree extracted/<pid>/<bid>/(uploads/ 保留供生命周期任务清)
    extracted_dir = Path(settings.extracted_dir) / str(project_id) / str(bidder_id)
    if extracted_dir.exists():
        shutil.rmtree(extracted_dir, ignore_errors=True)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------- GET /{bid}/documents (§5.1)

@router.get(
    "/{bidder_id}/documents",
    response_model=list[BidDocumentResponse],
)
async def list_bidder_documents(
    project_id: int,
    bidder_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[BidDocumentResponse]:
    """返投标人下的所有 bid_documents(归档行 + 解压条目混在一起)。

    前端按 ``file_type`` 过滤出归档 vs 文件,按 ``source_archive`` 分组拼树。
    """
    await _fetch_visible_bidder(session, user, project_id, bidder_id)
    rows = (
        await session.execute(
            select(BidDocument)
            .where(BidDocument.bidder_id == bidder_id)
            .order_by(BidDocument.created_at.asc())
        )
    ).scalars().all()
    return [BidDocumentResponse.model_validate(r) for r in rows]


__all__ = ["router"]
