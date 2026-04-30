"""招标文件路由 (detect-tender-baseline)。

prefix = ``/api/projects/{project_id}/tender``,挂在 main.py。所有端点
``Depends(get_current_user)`` + 项目级权限过滤(复用 C3 helper)。

端点对齐 spec ``file-upload`` Requirement:招标文件上传 / 列表与删除 / fail-soft。

设计要点:
- 与 BidDocument 上传链路解耦(D1 独立表,不污染 18 个 BidDocument 消费方)
- 落盘路径独立(``<upload_dir>/<pid>/tender/<tid>/<md5_prefix>_<safe_name>``)
- 上传成功后异步触发 ``trigger_extract(tender_id=...)``(D13 keyword-only 二选一)
- tender 解析跳过 LLM(file_role 固定 'tender',Q6 决策)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.project import Project, get_visible_projects_stmt
from app.models.tender_document import TenderDocument
from app.models.user import User
from app.schemas.tender import TenderDocumentResponse, TenderUploadResult
from app.services.extract import trigger_extract
from app.services.upload import (
    FileTooLarge,
    UnsupportedMediaType,
    save_tender_archive,
    validate_archive_file,
)

# 路由挂在 ``/api/projects/{project_id}/tender`` 前缀
router = APIRouter()


# --------------------------------------------------------------- 通用 helper

async def _fetch_visible_project(
    session: AsyncSession, user: User, project_id: int
) -> Project:
    """复用 C3 模式:未命中统一 404,不区分'不存在 / 无权 / 已软删'。"""
    stmt = get_visible_projects_stmt(user).where(Project.id == project_id)
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    return project


async def _peek_head_and_size(upload_file: UploadFile) -> tuple[bytes, int]:
    """与 bidders.py:_peek_head_and_size 等价,本地复制避免跨路由 import 噪音。"""
    head = await upload_file.read(64)
    upload_file.file.seek(0, 2)
    size = upload_file.file.tell()
    upload_file.file.seek(0)
    return head, size


async def _persist_tender_archive(
    *,
    session: AsyncSession,
    project: Project,
    upload_file: UploadFile,
) -> tuple[TenderDocument | None, str | None]:
    """处理一个 tender 上传:校验 → 落盘 → 写 tender_documents 行(pending)。

    Returns:
        ``(tender_row | None, dup_md5 | None)``:成功返第一个;项目内 MD5 已存在返第二个;
        其他校验失败抛 ``HTTPException``。
    """
    head, total_size = await _peek_head_and_size(upload_file)
    try:
        validate_archive_file(
            filename=upload_file.filename or "tender_archive",
            head_bytes=head,
            total_size=total_size,
        )
    except UnsupportedMediaType as exc:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)
        ) from exc
    except FileTooLarge as exc:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, str(exc)
        ) from exc

    # 注:save_tender_archive 用最终行的 tender_id 做路径分桶;但 insert 后才有
    # tender.id。简化:先 insert 占位 tender,拿 id 后再调 save_tender_archive,
    # 失败时回滚 + unlink。
    # 为避免占位与真正落盘之间的窗口,先算一个临时占位 path,落盘成功再 update。
    # 实操中:save_tender_archive 接受 tender_id 入参,直接传新 row.id。

    # 项目内 md5 dedupe 需先算 md5 — 把 save_tender_archive 拆成"算 md5 + 落盘"
    # 太重,此处采用"先落盘到临时 tender_id=0 路径不可行"。改用:先用 None 占位
    # 写 row(parse_status='pending'),flush 拿 id,再 save_tender_archive,成功
    # 后 update file_path/md5/size,失败回滚。
    placeholder = TenderDocument(
        project_id=project.id,
        file_name=upload_file.filename or "tender_archive",
        file_path="",  # 占位,落盘后填
        file_size=0,
        md5="",  # 占位
        parse_status="pending",
    )
    session.add(placeholder)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "tender 占位写入失败",
        ) from exc

    final_path: Path
    md5_hex: str
    total_bytes: int
    try:
        final_path, md5_hex, total_bytes = await save_tender_archive(
            project.id, placeholder.id, upload_file
        )
    except OSError as exc:
        await session.delete(placeholder)
        await session.commit()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"tender 落盘失败: {exc}",
        ) from exc

    # 项目内 MD5 已存在 → 删占位 + 物理文件 → 返 dup_md5
    existing = (
        await session.execute(
            select(TenderDocument.id).where(
                TenderDocument.project_id == project.id,
                TenderDocument.md5 == md5_hex,
                TenderDocument.id != placeholder.id,
                TenderDocument.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        await session.delete(placeholder)
        await session.commit()
        try:
            final_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None, md5_hex

    # 落盘成功,update 占位行
    placeholder.file_path = str(final_path)
    placeholder.file_size = total_bytes
    placeholder.md5 = md5_hex
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        try:
            final_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None, md5_hex
    return placeholder, None


# ---------------------------------------------------------- POST / 上传招标文件


@router.post(
    "/",
    response_model=TenderUploadResult,
    status_code=status.HTTP_201_CREATED,
)
async def upload_tender(
    project_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TenderUploadResult:
    """上传一份招标文件(docx / xlsx / zip)。"""
    project = await _fetch_visible_project(session, user, project_id)

    tender_row, dup_md5 = await _persist_tender_archive(
        session=session, project=project, upload_file=file
    )
    await session.commit()

    if tender_row is None:
        # 项目内 MD5 已存在 → 409
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"该招标文件已上传(md5={dup_md5})",
        )

    # 异步触发 tender 解析(D13 keyword-only 二选一)
    await trigger_extract(tender_id=tender_row.id)
    return TenderUploadResult(
        tender_id=tender_row.id,
        file_name=tender_row.file_name,
        parse_status=tender_row.parse_status,
    )


# ---------------------------------------------------------- GET / 列表


@router.get(
    "/",
    response_model=list[TenderDocumentResponse],
)
async def list_tenders(
    project_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TenderDocumentResponse]:
    """列出项目下所有未软删的招标文件。"""
    await _fetch_visible_project(session, user, project_id)
    rows = (
        await session.execute(
            select(TenderDocument)
            .where(
                TenderDocument.project_id == project_id,
                TenderDocument.deleted_at.is_(None),
            )
            .order_by(TenderDocument.created_at.desc())
        )
    ).scalars().all()
    return [TenderDocumentResponse.model_validate(r) for r in rows]


# ---------------------------------------------------------- DELETE 软删


@router.delete(
    "/{tender_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_tender(
    project_id: int,
    tender_id: int,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """软删除指定招标文件;baseline_resolver 之后将不再读取该 tender 的 hash。"""
    await _fetch_visible_project(session, user, project_id)
    tender = (
        await session.execute(
            select(TenderDocument).where(
                TenderDocument.id == tender_id,
                TenderDocument.project_id == project_id,
                TenderDocument.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if tender is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "招标文件不存在")

    tender.deleted_at = datetime.now(timezone.utc)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
