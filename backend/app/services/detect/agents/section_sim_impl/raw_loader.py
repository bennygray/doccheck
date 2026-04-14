"""C8 原始段落加载(不合并)

C7 segmenter.load_paragraphs_for_roles 对短段会 merge,破坏章节标题边界;
C8 章节级需要保留原始段落边界(每条 DocumentText 一段),故新增本 helper。
C7 代码零改动。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_text import DocumentText


async def load_raw_body_paragraphs(session: AsyncSession, doc_id: int) -> list[str]:
    """查 BidDocument.id=doc_id 的 body 段落,按 paragraph_index 升序,不合并。"""
    stmt = (
        select(DocumentText.text)
        .where(
            DocumentText.bid_document_id == doc_id,
            DocumentText.location == "body",
        )
        .order_by(DocumentText.paragraph_index.asc())
    )
    return [t for (t,) in (await session.execute(stmt)).all() if t and t.strip()]


__all__ = ["load_raw_body_paragraphs"]
