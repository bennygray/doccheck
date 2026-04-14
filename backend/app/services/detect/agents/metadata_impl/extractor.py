"""从 DocumentMetadata 批量 query bidder 元数据 (C10 metadata_impl)

由 3 metadata Agent 各自独立调用(不缓存共享,避免并发锁复杂度)。
每次返回 list[MetadataRecord],对每份 BidDocument 一条。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bid_document import BidDocument
from app.models.document_metadata import DocumentMetadata
from app.services.detect.agents.metadata_impl.models import MetadataRecord
from app.services.detect.agents.metadata_impl.normalizer import (
    nfkc_casefold_strip,
)


async def extract_bidder_metadata(
    session: AsyncSession, bidder_id: int
) -> list[MetadataRecord]:
    """返回 bidder 名下所有 BidDocument 的元数据快照(归一化后)。"""
    stmt = (
        select(BidDocument, DocumentMetadata)
        .join(
            DocumentMetadata,
            DocumentMetadata.bid_document_id == BidDocument.id,
        )
        .where(BidDocument.bidder_id == bidder_id)
    )
    rows = (await session.execute(stmt)).all()
    out: list[MetadataRecord] = []
    for bid_doc, meta in rows:
        out.append(
            {
                "bid_document_id": bid_doc.id,
                "bidder_id": bidder_id,
                "doc_name": bid_doc.file_name or "",
                "author_norm": nfkc_casefold_strip(meta.author),
                "last_saved_by_norm": nfkc_casefold_strip(meta.last_saved_by),
                "company_norm": nfkc_casefold_strip(meta.company),
                "template_norm": nfkc_casefold_strip(meta.template),
                "app_name": nfkc_casefold_strip(meta.app_name),
                "app_version": nfkc_casefold_strip(meta.app_version),
                "doc_created_at": meta.doc_created_at,
                "doc_modified_at": meta.doc_modified_at,
                "author_raw": meta.author,
                "last_saved_by_raw": meta.last_saved_by,
                "company_raw": meta.company,
                "template_raw": meta.template,
            }
        )
    return out


__all__ = ["extract_bidder_metadata"]
