"""C9 数据加载辅助。

- load_docx_titles_pair:跨两侧 bidder 找共享角色 docx 对,切章取标题
- load_xlsx_sheets_pair:跨两侧 bidder 找共享角色 xlsx 对,读 DocumentSheet

独立于 C7/C8 子包:C9 目录维度需 docx 章节标题、字段/填充维度需 xlsx sheets,
两者按文件类型分别匹配(不走 C8 ROLE_PRIORITY 仅文本优先的限制)。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bid_document import BidDocument
from app.models.document_sheet import DocumentSheet
from app.services.detect.agents.section_sim_impl import chapter_parser, raw_loader
from app.services.detect.agents.section_sim_impl import config as s8_config
from app.services.detect.agents.structure_sim_impl.field_sig import SheetInput


@dataclass(frozen=True)
class DocxPair:
    """一对共享角色的 docx 文档(+章节标题序列)。"""

    doc_role: str
    doc_id_a: int
    doc_id_b: int
    titles_a: list[str]
    titles_b: list[str]


@dataclass(frozen=True)
class XlsxPair:
    """一对共享角色的 xlsx 文档(+ DocumentSheet -> SheetInput 列表)。"""

    doc_role: str
    doc_id_a: int
    doc_id_b: int
    sheets_a: list[SheetInput]
    sheets_b: list[SheetInput]


async def _docs_for_bidder_by_ext(
    session: AsyncSession, bidder_id: int, ext: str
) -> dict[str, int]:
    """{file_role: bid_document_id}。同 role 多个 doc 取 id 最小(稳定排序)。"""
    stmt = (
        select(BidDocument.file_role, BidDocument.id)
        .where(
            BidDocument.bidder_id == bidder_id,
            BidDocument.file_type == ext,
            BidDocument.file_role.is_not(None),
            BidDocument.parse_status == "identified",
        )
        .order_by(BidDocument.id)
    )
    by_role: dict[str, int] = {}
    for role, doc_id in (await session.execute(stmt)).all():
        if role not in by_role:
            by_role[role] = doc_id
    return by_role


async def load_docx_titles_pair(
    session: AsyncSession, bidder_a_id: int, bidder_b_id: int
) -> DocxPair | None:
    """找两侧共享角色的 docx 对,复用 C8 chapter_parser 切章取 titles。

    多个共享角色时按 file_role 字典序取第一个(稳定,便于测试)。
    返 None 表示:无共享 docx 或切章后 titles 为空。
    """
    docs_a = await _docs_for_bidder_by_ext(session, bidder_a_id, ".docx")
    docs_b = await _docs_for_bidder_by_ext(session, bidder_b_id, ".docx")
    shared = sorted(set(docs_a.keys()) & set(docs_b.keys()))
    if not shared:
        return None

    role = shared[0]
    doc_id_a = docs_a[role]
    doc_id_b = docs_b[role]

    paras_a = await raw_loader.load_raw_body_paragraphs(session, doc_id_a)
    paras_b = await raw_loader.load_raw_body_paragraphs(session, doc_id_b)
    min_chapter_chars = s8_config.min_chapter_chars()
    chapters_a = chapter_parser.extract_chapters(paras_a, min_chapter_chars)
    chapters_b = chapter_parser.extract_chapters(paras_b, min_chapter_chars)
    titles_a = [c.title for c in chapters_a]
    titles_b = [c.title for c in chapters_b]

    return DocxPair(
        doc_role=role,
        doc_id_a=doc_id_a,
        doc_id_b=doc_id_b,
        titles_a=titles_a,
        titles_b=titles_b,
    )


async def _sheets_for_doc(
    session: AsyncSession, doc_id: int
) -> list[SheetInput]:
    stmt = (
        select(DocumentSheet)
        .where(DocumentSheet.bid_document_id == doc_id)
        .order_by(DocumentSheet.sheet_index)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        SheetInput(
            sheet_name=r.sheet_name,
            rows=list(r.rows_json or []),
            merged_cells=list(r.merged_cells_json or []),
        )
        for r in rows
    ]


async def load_xlsx_sheets_pair(
    session: AsyncSession, bidder_a_id: int, bidder_b_id: int
) -> XlsxPair | None:
    """找两侧共享角色的 xlsx 对,读 DocumentSheet 转 SheetInput。

    多个共享角色时按字典序取第一个。返 None 表示无共享 xlsx 或某侧无 DocumentSheet 行。
    """
    docs_a = await _docs_for_bidder_by_ext(session, bidder_a_id, ".xlsx")
    docs_b = await _docs_for_bidder_by_ext(session, bidder_b_id, ".xlsx")
    shared = sorted(set(docs_a.keys()) & set(docs_b.keys()))
    if not shared:
        return None

    role = shared[0]
    doc_id_a = docs_a[role]
    doc_id_b = docs_b[role]

    sheets_a = await _sheets_for_doc(session, doc_id_a)
    sheets_b = await _sheets_for_doc(session, doc_id_b)
    if not sheets_a or not sheets_b:
        return None

    return XlsxPair(
        doc_role=role,
        doc_id_a=doc_id_a,
        doc_id_b=doc_id_b,
        sheets_a=sheets_a,
        sheets_b=sheets_b,
    )
