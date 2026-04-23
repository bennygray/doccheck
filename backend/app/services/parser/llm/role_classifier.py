"""LLM 角色分类 + 投标人身份信息提取 (C5 parser-pipeline US-4.3)

一次 LLM 调用完成两个任务:
1. 为 bidder 下每个 DOCX/XLSX 文件确定 file_role(9 种之一)
2. 提取投标人身份信息 (identity_info JSONB)

LLM 失败兜底:
- 角色分类:fallback 到 role_keywords.classify_by_keywords(所有文档置 role_confidence='low')
- 身份信息:置 NULL(不做规则兜底,避免精度差导致污染)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_text import DocumentText
from app.services.llm.base import LLMProvider
from app.services.parser.llm.prompts import (
    ROLE_CLASSIFY_SYSTEM_PROMPT,
    ROLE_CLASSIFY_USER_TEMPLATE,
)
from app.services.parser.llm.role_keywords import (
    classify_by_keywords,
    classify_by_keywords_on_text,
)

logger = logging.getLogger(__name__)

VALID_ROLES = frozenset(
    {
        "technical",
        "construction",
        "pricing",
        "unit_price",
        "bid_letter",
        "qualification",
        "company_intro",
        "authorization",
        "other",
    }
)


@dataclass(frozen=True)
class ClassifyResult:
    # 是否成功走 LLM 分支(True) vs 走规则兜底(False)
    llm_used: bool
    # 所有文档的 role 已写入 DB
    documents_updated: int


async def classify_bidder(
    session: AsyncSession,
    bidder_id: int,
    llm: LLMProvider,
) -> ClassifyResult:
    """为 bidder 批量分类 + 身份信息提取;LLM 错走规则兜底。

    C6 起外层包 ``async with track()``;系统重启导致分类任务中断时,
    scanner 扫到 stuck 后把 bidder.parse_status 从 identifying 回滚到 identify_failed。
    """
    # 延迟导入避免循环依赖
    from app.services.async_tasks.tracker import track

    async with track(
        subtype="llm_classify",
        entity_type="bidder",
        entity_id=bidder_id,
    ):
        return await _classify_bidder_inner(session, bidder_id, llm)


async def _classify_bidder_inner(
    session: AsyncSession,
    bidder_id: int,
    llm: LLMProvider,
) -> ClassifyResult:
    """原 classify_bidder 主体。"""
    # 收集该 bidder 的 DOCX/XLSX 文件(仅 identified 文件,即内容已提取完)
    stmt = (
        select(BidDocument)
        .where(BidDocument.bidder_id == bidder_id)
        .where(BidDocument.file_type.in_([".docx", ".xlsx"]))
    )
    docs = (await session.execute(stmt)).scalars().all()
    if not docs:
        return ClassifyResult(llm_used=False, documents_updated=0)

    # 构造 LLM 输入:每个文档首段文本(前 500 字符)
    files_block_parts: list[str] = []
    for doc in docs:
        first_text = await _get_first_paragraph(session, doc.id)
        snippet = (first_text or "")[:500]
        files_block_parts.append(
            f"- document_id={doc.id}  name={doc.file_name!r}\n  first_text: {snippet}"
        )
    files_block = "\n".join(files_block_parts)

    user_msg = ROLE_CLASSIFY_USER_TEMPLATE.format(
        file_count=len(docs), files_block=files_block
    )

    result = await llm.complete(
        messages=[
            {"role": "system", "content": ROLE_CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )

    if result.error is not None:
        # harden-async-infra N7:保留 classify_by_keywords 兜底(现有设计,解析流水线
        # 不中断);日志精细化 kind 供 N3 explore 分析大文档场景 LLM 根因占比。
        logger.warning(
            "role_classifier LLM error kind=%s msg=%s; fallback to keywords",
            result.error.kind,
            result.error.message,
        )
        await _apply_keyword_fallback(session, docs)
        await session.commit()
        return ClassifyResult(llm_used=False, documents_updated=len(docs))

    parsed = _parse_llm_json(result.text)
    if parsed is None:
        logger.warning(
            "role_classifier LLM returned invalid JSON; fallback to keywords"
        )
        await _apply_keyword_fallback(session, docs)
        await session.commit()
        return ClassifyResult(llm_used=False, documents_updated=len(docs))

    # 应用 LLM 结果
    roles_map: dict[int, tuple[str, str]] = {}
    for item in parsed.get("roles", []):
        doc_id = item.get("document_id")
        role = item.get("role")
        confidence = item.get("confidence", "high")
        if isinstance(doc_id, int) and role in VALID_ROLES:
            conf = confidence if confidence in ("high", "low") else "high"
            roles_map[doc_id] = (role, conf)

    missing_docs: list[BidDocument] = []
    for doc in docs:
        if doc.id in roles_map:
            role, conf = roles_map[doc.id]
            doc.file_role = role
            doc.role_confidence = conf
        else:
            missing_docs.append(doc)

    # LLM 漏返的文档走规则兜底
    if missing_docs:
        await _apply_keyword_fallback(session, missing_docs)

    # 身份信息 → bidder.identity_info
    identity = parsed.get("identity_info")
    if isinstance(identity, dict) and identity:
        # 过滤掉空 string value
        cleaned = {
            k: v for k, v in identity.items() if v not in (None, "", [])
        }
        if cleaned:
            bidder = await session.get(Bidder, bidder_id)
            if bidder is not None:
                bidder.identity_info = cleaned

    await session.commit()
    return ClassifyResult(llm_used=True, documents_updated=len(docs))


async def _apply_keyword_fallback(
    session: AsyncSession, docs: list[BidDocument]
) -> None:
    """两级关键词兜底(fix-mac-packed-zip-parsing 3.2):

    1. 若 doc.parse_status == 'identified',先读首段正文 ≤1000 字,调
       ``classify_by_keywords_on_text`` 做正文关键词匹配;命中即用该 role。
    2. 未命中(或非 identified)再调 ``classify_by_keywords(file_name)``。
    3. 仍未命中 → role='other'。

    所有兜底路径一律 ``role_confidence='low'``。
    """
    for doc in docs:
        role: str | None = None
        if doc.parse_status == "identified":
            first_text = await _get_first_paragraph(session, doc.id)
            if first_text:
                role = classify_by_keywords_on_text(first_text[:1000])
        if role is None:
            role = classify_by_keywords(doc.file_name or "")
        doc.file_role = role or "other"
        doc.role_confidence = "low"


async def _get_first_paragraph(
    session: AsyncSession, bid_document_id: int
) -> str | None:
    stmt = (
        select(DocumentText.text)
        .where(DocumentText.bid_document_id == bid_document_id)
        .where(DocumentText.location.in_(["body", "sheet"]))
        .order_by(DocumentText.paragraph_index)
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    return row


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    """解析 LLM 输出为 dict;兼容包裹 ```json``` 代码块。"""
    if not text:
        return None
    s = text.strip()
    # 去掉可能的 markdown 代码块包裹
    if s.startswith("```"):
        lines = s.splitlines()
        # 去掉首尾 fence
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            s = "\n".join(lines).strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
        return None
    except json.JSONDecodeError:
        return None


__all__ = ["classify_bidder", "ClassifyResult", "VALID_ROLES"]
