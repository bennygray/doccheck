"""文档内容提取入口 (C5 parser-pipeline US-4.2)

按 file_type 分派到 docx/xlsx/metadata/image 子 extractor,写入:
- document_texts / document_metadata / document_images 三张表

副作用:更新 bid_document.parse_status (identifying → identified / identify_failed / skipped)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bid_document import BidDocument
from app.models.document_image import DocumentImage
from app.models.document_metadata import DocumentMetadata
from app.models.document_text import DocumentText
from app.services.parser.content.docx_parser import extract_docx
from app.services.parser.content.image_parser import extract_images_from_docx
from app.services.parser.content.metadata_parser import extract_metadata
from app.services.parser.content.xlsx_parser import extract_xlsx

logger = logging.getLogger(__name__)

_SUPPORTED = {".docx", ".xlsx"}
_SKIPPED = {".doc", ".xls", ".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".gif"}

# .jpg/.png 等图片目前作为独立文件类型标 skipped(嵌入图在 docx 内处理)
# 图片文件独立上传的解析留 C17+;当前阶段只接受 DOCX 嵌入图


async def extract_content(
    session: AsyncSession, bid_document_id: int
) -> None:
    """按 file_type 分派解析 + 落盘。失败兜底到 identify_failed。"""
    doc = await session.get(BidDocument, bid_document_id)
    if doc is None:
        logger.warning("extract_content: document %d not found", bid_document_id)
        return

    ext = (doc.file_type or "").lower()
    if ext not in _SUPPORTED:
        if ext in _SKIPPED:
            doc.parse_status = "skipped"
            doc.parse_error = f"暂不支持 {ext} 格式"
        else:
            doc.parse_status = "skipped"
            doc.parse_error = f"未知文件类型 {ext}"
        await session.commit()
        return

    # 清空旧提取结果(re-parse 场景)
    await _clean_prior_extraction(session, bid_document_id)

    doc.parse_status = "identifying"
    await session.commit()

    try:
        file_path = Path(doc.file_path)
        if not file_path.exists():
            doc.parse_status = "identify_failed"
            doc.parse_error = "物理文件不存在"
            await session.commit()
            return

        # I/O 密集操作卸到线程池
        if ext == ".docx":
            result = await asyncio.to_thread(extract_docx, file_path)
            for block in result.blocks:
                session.add(
                    DocumentText(
                        bid_document_id=bid_document_id,
                        paragraph_index=block.paragraph_index,
                        text=block.text,
                        location=block.location,
                    )
                )
            # 嵌入图
            img_out = file_path.parent / "imgs"
            images = await asyncio.to_thread(
                extract_images_from_docx, file_path, img_out
            )
            for img in images:
                session.add(
                    DocumentImage(
                        bid_document_id=bid_document_id,
                        file_path=img.file_path,
                        md5=img.md5,
                        phash=img.phash,
                        width=img.width,
                        height=img.height,
                        position=img.position,
                    )
                )
        elif ext == ".xlsx":
            result = await asyncio.to_thread(extract_xlsx, file_path)
            for i, sheet in enumerate(result.sheets):
                session.add(
                    DocumentText(
                        bid_document_id=bid_document_id,
                        paragraph_index=i,
                        text=sheet.merged_text,
                        location="sheet",
                    )
                )

        # 元数据(docx/xlsx 共用)
        meta = await asyncio.to_thread(extract_metadata, file_path)
        session.add(
            DocumentMetadata(
                bid_document_id=bid_document_id,
                author=meta.author,
                last_saved_by=meta.last_saved_by,
                company=meta.company,
                doc_created_at=meta.created_at,
                doc_modified_at=meta.modified_at,
                app_name=meta.app_name,
                app_version=meta.app_version,
            )
        )

        doc.parse_status = "identified"
        doc.parse_error = None
        await session.commit()

    except Exception as e:
        logger.exception("extract_content failed doc=%d", bid_document_id)
        # 滚回之前未提交的 add
        await session.rollback()
        doc = await session.get(BidDocument, bid_document_id)
        if doc is not None:
            doc.parse_status = "identify_failed"
            doc.parse_error = str(e)[:500]
            await session.commit()


async def _clean_prior_extraction(
    session: AsyncSession, bid_document_id: int
) -> None:
    """清掉该文档之前的 document_texts / metadata / images(re-parse 用)。"""
    await session.execute(
        delete(DocumentText).where(DocumentText.bid_document_id == bid_document_id)
    )
    await session.execute(
        delete(DocumentMetadata).where(
            DocumentMetadata.bid_document_id == bid_document_id
        )
    )
    await session.execute(
        delete(DocumentImage).where(DocumentImage.bid_document_id == bid_document_id)
    )
    await session.commit()


__all__ = ["extract_content"]
