"""style 抽样器 (C13)

每 bidder 的 technical 角色文档段落:
1) TF-IDF 训练全语料,过滤低 IDF(高频通用)段落
2) 长度过滤 100~300 字
3) 均匀抽 SAMPLE_PER_BIDDER 段(贴 spec L-8)

不足 min_sample(默认 3)段时标 insufficient_sample。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bid_document import BidDocument
from app.models.document_text import DocumentText
from app.services.detect.agents.style_impl.config import StyleConfig

logger = logging.getLogger(__name__)

_TECHNICAL_ROLE = "technical"
_MIN_PARA_LEN = 100
_MAX_PARA_LEN = 300
_INSUFFICIENT_THRESHOLD = 3


async def _load_paragraphs(
    session: AsyncSession, bidder_id: int
) -> list[str]:
    """读 bidder 的 technical 文档段落(仅 location='body')。"""
    stmt = (
        select(DocumentText.text)
        .select_from(DocumentText)
        .join(BidDocument, DocumentText.bid_document_id == BidDocument.id)
        .where(
            BidDocument.bidder_id == bidder_id,
            BidDocument.file_role == _TECHNICAL_ROLE,
            DocumentText.location == "body",
        )
    )
    rows = (await session.execute(stmt)).all()
    return [r[0] for r in rows if r[0]]


def _length_filter(paragraphs: list[str]) -> list[str]:
    """100~300 字范围保留;过短丢、过长截断。"""
    out: list[str] = []
    for p in paragraphs:
        n = len(p)
        if n < _MIN_PARA_LEN:
            continue
        if n > _MAX_PARA_LEN:
            out.append(p[:_MAX_PARA_LEN])
        else:
            out.append(p)
    return out


def _tfidf_filter(
    paragraphs: list[str], filter_ratio: float
) -> list[str]:
    """用 TF-IDF 过滤掉低 IDF(高频通用)段落。

    filter_ratio=0.3 表示保留 IDF 排名前 70% 的段落(过滤掉低 30%)。
    段落数 < 3 时不过滤(语料不足无法训练有意义模型)。
    """
    if len(paragraphs) < 3 or filter_ratio <= 0:
        return paragraphs

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        logger.warning("sklearn not available, skip tfidf filter")
        return paragraphs

    try:
        # token_pattern 用 jieba 简化:按字符拆 (中文 OK,通用回退)
        vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 3),
            max_features=5000,
            min_df=1,
        )
        matrix = vectorizer.fit_transform(paragraphs)
        # 每段平均 TF-IDF 权重(低 = 高频通用)
        avg_tfidf = matrix.mean(axis=1).A.flatten()
    except Exception as e:  # noqa: BLE001
        logger.warning("tfidf filter failed: %s", e)
        return paragraphs

    if len(avg_tfidf) == 0:
        return paragraphs
    sorted_idx = sorted(range(len(avg_tfidf)), key=lambda i: avg_tfidf[i])
    cut = int(len(sorted_idx) * filter_ratio)
    keep_idx = set(sorted_idx[cut:])
    return [paragraphs[i] for i in range(len(paragraphs)) if i in keep_idx]


def _uniform_sample(paragraphs: list[str], n: int) -> list[str]:
    """均匀步长抽样(贴 spec L-8 "均匀抽样")。"""
    if len(paragraphs) <= n:
        return paragraphs
    step = len(paragraphs) / n
    return [paragraphs[int(i * step)] for i in range(n)]


async def sample(
    session: AsyncSession, bidder_id: int, cfg: StyleConfig
) -> tuple[list[str], bool]:
    """抽样产出 (paragraphs, insufficient_sample)。

    insufficient_sample = True 当抽样后段数 < _INSUFFICIENT_THRESHOLD。
    """
    raw = await _load_paragraphs(session, bidder_id)
    filtered_len = _length_filter(raw)
    filtered_tfidf = _tfidf_filter(filtered_len, cfg.tfidf_filter_ratio)
    sampled = _uniform_sample(filtered_tfidf, cfg.sample_per_bidder)
    insufficient = len(sampled) < _INSUFFICIENT_THRESHOLD
    return sampled, insufficient


__all__ = ["sample"]
