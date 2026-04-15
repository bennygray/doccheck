"""error_consistency 跨投标人关键词交叉搜索 (C13)

对 pair (A, B):用 A 的关键词在 B 的 document_texts(body/header/footer 段落)做子串匹配,
反向亦然;双向命中合并去重。
候选段落总数上限 MAX_CANDIDATE_SEGMENTS(RISK-19 token 爆炸防护)。

注意:apply 现场修正 — document_texts 实际是行级表(location 字段区分 body/header/footer),
非 spec 写的 paragraphs/header_footer JSONB 数组;直接 SQL 查行,语义等价。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bid_document import BidDocument
from app.models.document_text import DocumentText
from app.services.detect.agents.error_impl.config import ErrorConsistencyConfig
from app.services.detect.agents.error_impl.models import SuspiciousSegment


# 仅消费这三类 location 段落(贴 spec §F-DA-02 "正文 + 页眉页脚")
_SEARCH_LOCATIONS = ("body", "header", "footer", "textbox", "table_row")


async def _load_segments(
    session: AsyncSession, bidder_id: int
) -> list[tuple[int, int, str | None, str, str]]:
    """加载 bidder 全部可搜段落;返 (text_id, doc_id, doc_role, location, text) tuple 列表。"""
    stmt = (
        select(
            DocumentText.id,
            DocumentText.bid_document_id,
            BidDocument.file_role,
            DocumentText.location,
            DocumentText.text,
        )
        .select_from(DocumentText)
        .join(BidDocument, DocumentText.bid_document_id == BidDocument.id)
        .where(
            BidDocument.bidder_id == bidder_id,
            DocumentText.location.in_(_SEARCH_LOCATIONS),
        )
    )
    rows = (await session.execute(stmt)).all()
    return [tuple(r) for r in rows]  # type: ignore[misc]


def _scan_segments(
    segments: list[tuple[int, int, str | None, str, str]],
    keywords: list[str],
    source_bidder_id: int,
) -> list[SuspiciousSegment]:
    """单向扫描:keywords 是 source_bidder 的;在对面 bidder 的 segments 里找命中。"""
    out: list[SuspiciousSegment] = []
    for _text_id, doc_id, doc_role, location, text in segments:
        matched: list[str] = []
        for kw in keywords:
            if kw in text:
                matched.append(kw)
        if matched:
            # 段落归位:body/textbox/table_row → "body" 大类;header/footer 保留
            position = location if location in ("header", "footer") else "body"
            out.append(
                SuspiciousSegment(
                    paragraph_text=text,
                    doc_id=doc_id,
                    doc_role=doc_role,
                    position=position,
                    matched_keywords=matched,
                    source_bidder_id=source_bidder_id,
                )
            )
    return out


def _truncate(
    hits: list[SuspiciousSegment], cap: int
) -> tuple[list[SuspiciousSegment], bool, int]:
    """按 matched_keywords 数倒序截断到 cap。返 (hits, truncated, original_count)。"""
    original = len(hits)
    if original <= cap:
        return hits, False, original
    sorted_hits = sorted(
        hits, key=lambda h: len(h["matched_keywords"]), reverse=True
    )
    return sorted_hits[:cap], True, original


async def search(
    session: AsyncSession,
    bidder_a_id: int,
    bidder_b_id: int,
    keywords_a: list[str],
    keywords_b: list[str],
    cfg: ErrorConsistencyConfig,
) -> tuple[list[SuspiciousSegment], bool, int]:
    """双向交叉搜索。返 (suspicious_segments, truncated, original_count)。"""
    if not keywords_a and not keywords_b:
        return [], False, 0

    segs_a = await _load_segments(session, bidder_a_id) if keywords_b else []
    segs_b = await _load_segments(session, bidder_b_id) if keywords_a else []

    hits: list[SuspiciousSegment] = []
    if keywords_a:
        hits.extend(_scan_segments(segs_b, keywords_a, bidder_a_id))
    if keywords_b:
        hits.extend(_scan_segments(segs_a, keywords_b, bidder_b_id))

    return _truncate(hits, cfg.max_candidate_segments)


__all__ = ["search"]
