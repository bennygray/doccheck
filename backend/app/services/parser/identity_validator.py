"""Identity 规则校验(parser-accuracy-fixes P0-1)

用途:LLM 抽 identity_info.company_full_name 有时会把招标方/项目名误当投标方。
本模块在 LLM 返回后做一步正则校验:扫 docx body 段找 "投标人(盖章):" 后的公司名,
与 LLM 结果比对,不一致则规则覆盖 + 审计 LLM 原值 + role_confidence 降级 low。

为什么是后置规则(而不是前置):
    LLM 在多文档上下文下柔性好(能抽简称/部分匹配),规则刚性但对模板文字依赖强。
    "先 LLM 再规则"策略:LLM 正常工作时规则静默;LLM 跑偏时规则纠偏。

Scope:只扫 file_type='.docx' 且 location='body' 的段落。
    不扫 textbox(盖章章样常在那里,但位置无保证);不扫 header/footer。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_text import DocumentText

logger = logging.getLogger(__name__)


# 正则模式说明:
# - 匹配 "投标人(盖章):XXX" / "投标人（盖章）：XXX" / "投标人 盖章 : XXX" 等变体
# - 括号(中英全半角)可选;冒号中英均可;空白允许
# - non-greedy `(.+?)` 吃公司名到尾终止符
# - 尾终止:换行 \n / ≥2 空格 / 字符串结束 $
_BIDDER_NAME_RE = re.compile(
    r"投标人\s*[（(]?\s*盖章\s*[）)]?\s*[:：]\s*(.+?)(?:\n|\s{2,}|$)"
)


async def extract_bidder_name_by_rule(
    session: AsyncSession, bidder_id: int
) -> str | None:
    """扫 bidder 下所有 .docx 的 body 段,正则找 "投标人(盖章):" 后的公司名。

    返回首次命中结果(按 paragraph_index 升序遍历);全未命中返 None。
    """
    stmt = (
        select(DocumentText.text)
        .join(BidDocument, BidDocument.id == DocumentText.bid_document_id)
        .where(BidDocument.bidder_id == bidder_id)
        .where(BidDocument.file_type == ".docx")
        .where(DocumentText.location == "body")
        .order_by(BidDocument.id, DocumentText.paragraph_index)
    )
    rows = (await session.execute(stmt)).scalars().all()

    for text in rows:
        if not text:
            continue
        match = _BIDDER_NAME_RE.search(text)
        if match:
            name = match.group(1).strip()
            if name:
                return name
    return None


def _match_identity(
    llm_name: str | None, rule_name: str | None
) -> str:
    """返回决策:
    - "match":一致(相等或满足子串条件)→ 保留 LLM,不动 role_confidence
    - "fill":LLM 空 + 规则命中 → 用规则**补齐** company_full_name,不动 role_confidence(spec 契约:补齐 ≠ 纠正)
    - "mismatch":两者不一致 → 规则覆盖 + 审计 + role_confidence 降级 low
    - "unmatched":规则未命中 → 保留 LLM,不动 role_confidence

    子串判定(review M4 修):加最短长度 guard(SUBSTRING_MIN_LEN=4),
    防止"华建" in "江苏华建建设"误命中另一家相同子串公司。
    """
    if rule_name is None:
        return "unmatched"
    if not llm_name:
        return "fill"  # review H1 修:补齐不是纠正,和 mismatch 分开
    # 归一化:去空白(含全角空格)
    l = "".join(llm_name.split()).replace("\u3000", "")
    r = "".join(rule_name.split()).replace("\u3000", "")
    if l == r:
        return "match"
    # review M4:子串等价仅当短串 ≥ SUBSTRING_MIN_LEN 字,防短串假阳
    if len(l) >= SUBSTRING_MIN_LEN and l in r:
        return "match"
    if len(r) >= SUBSTRING_MIN_LEN and r in l:
        return "match"
    return "mismatch"


SUBSTRING_MIN_LEN = 4  # review M4


async def apply_identity_validation(
    session: AsyncSession, bidder_id: int
) -> None:
    """在 classify_bidder 完成后调用。按规则-LLM 比对结果更新 bidder.identity_info。

    - match / 一致:保留 LLM,无动作
    - mismatch / 不一致:规则覆盖 company_full_name;审计 LLM 原值到 _llm_original;
      该 bidder 所有 docx/xlsx 的 role_confidence 降级 low
    - unmatched / 规则未命中:保留 LLM,无动作
    - LLM 空 + 规则命中:rule 值直接填 company_full_name(无审计字段)
    """
    bidder = await session.get(Bidder, bidder_id)
    if bidder is None:
        return

    rule_name = await extract_bidder_name_by_rule(session, bidder_id)

    identity_info = dict(bidder.identity_info or {})
    llm_name = identity_info.get("company_full_name")

    decision = _match_identity(llm_name, rule_name)

    if decision == "match":
        logger.info(
            "identity_validator bidder=%d match: llm=%r rule=%r",
            bidder_id, llm_name, rule_name,
        )
        return

    if decision == "unmatched":
        logger.info(
            "identity_validator bidder=%d rule unmatched, keep LLM: llm=%r",
            bidder_id, llm_name,
        )
        return

    if decision == "fill":
        # review H1 修:LLM 空 + 规则命中 = 补齐,不是纠正
        # 只写 company_full_name;不写 _llm_original 审计;不降级 role_confidence
        logger.info(
            "identity_validator bidder=%d fill: rule=%r (llm had no company name)",
            bidder_id, rule_name,
        )
        identity_info["company_full_name"] = rule_name
        bidder.identity_info = identity_info
        return

    # decision == "mismatch"
    logger.warning(
        "identity_validator bidder=%d override: llm=%r -> rule=%r",
        bidder_id, llm_name, rule_name,
    )

    # 规则覆盖 company_full_name;LLM 原值存 _llm_original 审计
    identity_info["_llm_original"] = llm_name
    identity_info["company_full_name"] = rule_name
    bidder.identity_info = identity_info

    # 该 bidder 所有 docx/xlsx 的 role_confidence 降级 low
    stmt = (
        select(BidDocument)
        .where(BidDocument.bidder_id == bidder_id)
        .where(BidDocument.file_type.in_([".docx", ".xlsx"]))
    )
    docs = (await session.execute(stmt)).scalars().all()
    for doc in docs:
        doc.role_confidence = "low"


__all__ = [
    "extract_bidder_name_by_rule",
    "apply_identity_validation",
    "_match_identity",
    "_BIDDER_NAME_RE",
]
