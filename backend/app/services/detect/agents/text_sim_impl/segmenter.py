"""段落加载与切分 (C7 detect-agent-text-similarity)

职责:
- 从 DocumentText 读 body 段落(页眉/页脚/文本框/表格行不参与文本相似度;
  与 C5 US-4.2 AC-3 "页眉页脚不参与相似度" 对齐)
- 按 ROLE_PRIORITY 选择双方共有的、优先级最高的 file_role
- 合并相邻过短段落(< MIN_PARAGRAPH_CHARS)
- 计算 total_chars,供 preflight 判"文档过短"
"""

from __future__ import annotations

from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bid_document import BidDocument
from app.models.document_text import DocumentText

# 选择 file_role 的优先级:越靠前越优先,跳过不适合文本相似度的角色
# - pricing / unit_price : 数字为主,文本相似度无意义
# - qualification / authorization : 定型文书,抄袭无区分力
# - 其他按 "content 量级 + 自由撰写比例" 排
ROLE_PRIORITY: tuple[str, ...] = (
    "technical",      # 技术方案 — 最理想
    "construction",   # 施工组织
    "bid_letter",     # 投标函
    "company_intro",  # 企业介绍
    "other",          # 未分类
)

# 短段合并阈值(字符数)
MIN_PARAGRAPH_CHARS = 50


class SegmentResult(NamedTuple):
    """单侧 bidder 的段落加载结果。"""

    doc_role: str | None   # 选中的 file_role;无可比对文档时 None
    doc_id: int | None     # 选中的 BidDocument.id;无时 None
    paragraphs: list[str]  # 合并短段后的段落列表
    total_chars: int       # 所有段落字符总数


async def load_paragraphs_for_roles(
    session: AsyncSession, bidder_id: int, allowed_roles: list[str]
) -> SegmentResult:
    """按 allowed_roles 的顺序选第一个有 BidDocument 的 role,加载其段落。

    allowed_roles 由 pair 两侧的共有 role 集合按 ROLE_PRIORITY 过滤+排序得到。
    """
    if not allowed_roles:
        return SegmentResult(None, None, [], 0)

    # 选 allowed_roles[0](已按优先级排序)的第一份文档
    role = allowed_roles[0]
    stmt = (
        select(BidDocument.id)
        .where(BidDocument.bidder_id == bidder_id, BidDocument.file_role == role)
        .order_by(BidDocument.id.asc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        # 当前 role 无文档(理论上不会发生,调用方保证双方都有),
        # 递归尝试下一个 role
        return await load_paragraphs_for_roles(
            session, bidder_id, allowed_roles[1:]
        )

    doc_id = row

    # 只取 body 段落,按 paragraph_index 升序
    stmt = (
        select(DocumentText.text)
        .where(
            DocumentText.bid_document_id == doc_id,
            DocumentText.location == "body",
        )
        .order_by(DocumentText.paragraph_index.asc())
    )
    texts = [t for (t,) in (await session.execute(stmt)).all() if t and t.strip()]
    merged = _merge_short_paragraphs(texts, MIN_PARAGRAPH_CHARS)
    total = sum(len(p) for p in merged)
    return SegmentResult(
        doc_role=role, doc_id=doc_id, paragraphs=merged, total_chars=total
    )


async def choose_shared_role(
    session: AsyncSession, bidder_a_id: int, bidder_b_id: int
) -> list[str]:
    """返两 bidder 共有 file_role 的列表,按 ROLE_PRIORITY 优先级排序。

    不在 ROLE_PRIORITY 内的角色(pricing / qualification 等)被过滤掉。
    """
    stmt = select(BidDocument.file_role).where(
        BidDocument.bidder_id == bidder_a_id,
        BidDocument.file_role.is_not(None),
    )
    roles_a = {r for (r,) in (await session.execute(stmt)).all() if r}
    stmt = select(BidDocument.file_role).where(
        BidDocument.bidder_id == bidder_b_id,
        BidDocument.file_role.is_not(None),
    )
    roles_b = {r for (r,) in (await session.execute(stmt)).all() if r}
    shared = roles_a & roles_b
    return [r for r in ROLE_PRIORITY if r in shared]


def _merge_short_paragraphs(texts: list[str], min_chars: int) -> list[str]:
    """合并相邻短段落,直到累积字符数 ≥ min_chars 或到末尾。

    合并时用换行连接,保留段落边界供 LLM 看清上下文。
    """
    if not texts:
        return []
    merged: list[str] = []
    buf = ""
    for t in texts:
        buf = (buf + "\n" + t).strip() if buf else t.strip()
        if len(buf) >= min_chars:
            merged.append(buf)
            buf = ""
    if buf:
        # 末尾残留 → 合并进最后一段(若存在)避免产生单独的超短段
        if merged:
            merged[-1] = merged[-1] + "\n" + buf
        else:
            # 整份文档字符不够 min_chars,仍返回这一条(让 total_chars 判短 skip)
            merged.append(buf)
    return merged


__all__ = [
    "ROLE_PRIORITY",
    "MIN_PARAGRAPH_CHARS",
    "SegmentResult",
    "load_paragraphs_for_roles",
    "choose_shared_role",
]
