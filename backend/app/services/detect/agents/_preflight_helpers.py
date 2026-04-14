"""preflight 共享辅助查询 (C6 detect-framework)

各 Agent 的 preflight 需要查询文档/元数据/图片等项目状态。
集中放这里避免 10x 重复 query 样板。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bid_document import BidDocument
from app.models.document_image import DocumentImage
from app.models.document_metadata import DocumentMetadata
from app.models.price_item import PriceItem


async def bidder_has_role(
    session: AsyncSession, bidder_id: int, role: str | None = None
) -> bool:
    """投标人是否有 file_role 非空(或指定 role)的 bid_document。"""
    stmt = select(func.count(BidDocument.id)).where(
        BidDocument.bidder_id == bidder_id
    )
    if role is not None:
        stmt = stmt.where(BidDocument.file_role == role)
    else:
        stmt = stmt.where(BidDocument.file_role.is_not(None))
    result = await session.execute(stmt)
    return (result.scalar() or 0) > 0


async def bidders_share_any_role(
    session: AsyncSession, bidder_a_id: int, bidder_b_id: int
) -> bool:
    """两 bidder 是否存在共同的 file_role(即同角色可对比文档)。"""
    stmt_a = select(BidDocument.file_role).where(
        BidDocument.bidder_id == bidder_a_id,
        BidDocument.file_role.is_not(None),
    )
    stmt_b = select(BidDocument.file_role).where(
        BidDocument.bidder_id == bidder_b_id,
        BidDocument.file_role.is_not(None),
    )
    roles_a = {r for (r,) in (await session.execute(stmt_a)).all()}
    roles_b = {r for (r,) in (await session.execute(stmt_b)).all()}
    return bool(roles_a & roles_b)


async def bidder_has_metadata(
    session: AsyncSession,
    bidder_id: int,
    require_field: str | None = None,
) -> bool:
    """投标人是否有 document_metadata 行(可选要求某字段非空)。"""
    stmt = (
        select(func.count(DocumentMetadata.bid_document_id))
        .select_from(DocumentMetadata)
        .join(
            BidDocument,
            DocumentMetadata.bid_document_id == BidDocument.id,
        )
        .where(BidDocument.bidder_id == bidder_id)
    )
    if require_field == "author":
        stmt = stmt.where(DocumentMetadata.author.is_not(None))
    elif require_field == "modified":
        stmt = stmt.where(DocumentMetadata.doc_modified_at.is_not(None))
    elif require_field == "machine":
        stmt = stmt.where(
            (DocumentMetadata.app_version.is_not(None))
            | (DocumentMetadata.app_name.is_not(None))
            | (DocumentMetadata.template.is_not(None))
        )
    result = await session.execute(stmt)
    return (result.scalar() or 0) > 0


async def bidder_has_priced(
    session: AsyncSession, bidder_id: int
) -> bool:
    """投标人是否有 price_items 行(C5 回填成功的 priced / price_partial)。"""
    stmt = select(func.count(PriceItem.id)).where(
        PriceItem.bidder_id == bidder_id
    )
    result = await session.execute(stmt)
    return (result.scalar() or 0) > 0


async def bidder_has_images(
    session: AsyncSession, bidder_id: int
) -> bool:
    """投标人是否有 document_images 行。"""
    stmt = (
        select(func.count(DocumentImage.id))
        .select_from(DocumentImage)
        .join(
            BidDocument,
            DocumentImage.bid_document_id == BidDocument.id,
        )
        .where(BidDocument.bidder_id == bidder_id)
    )
    result = await session.execute(stmt)
    return (result.scalar() or 0) > 0


async def bidders_share_role_with_ext(
    session: AsyncSession,
    bidder_a_id: int,
    bidder_b_id: int,
    exts: set[str],
) -> bool:
    """两 bidder 是否存在"共同 file_role 且双方都有 exts 之一"的文档对。

    C9 结构维度 preflight 用:只要"有 docx 可对比"或"有 xlsx 可对比"之一即可。
    """
    stmt_a = select(BidDocument.file_role).where(
        BidDocument.bidder_id == bidder_a_id,
        BidDocument.file_role.is_not(None),
        BidDocument.file_type.in_(exts),
    )
    stmt_b = select(BidDocument.file_role).where(
        BidDocument.bidder_id == bidder_b_id,
        BidDocument.file_role.is_not(None),
        BidDocument.file_type.in_(exts),
    )
    roles_a = {r for (r,) in (await session.execute(stmt_a)).all()}
    roles_b = {r for (r,) in (await session.execute(stmt_b)).all()}
    return bool(roles_a & roles_b)


__all__ = [
    "bidder_has_role",
    "bidders_share_any_role",
    "bidders_share_role_with_ext",
    "bidder_has_metadata",
    "bidder_has_priced",
    "bidder_has_images",
]
