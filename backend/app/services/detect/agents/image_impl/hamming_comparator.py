"""image_reuse MD5 + pHash 双路比较 (C13)

1) 小图过滤:SQL WHERE width >= MIN_WIDTH AND height >= MIN_HEIGHT
2) 跨 bidder 两两组合:对每对 (A, B):
   a. MD5 INNER JOIN → byte_match(hit_strength=1.0)
   b. 剩余图(MD5 未命中)做 pHash Hamming distance 比较 → visual_similar(hit_strength=1-d/64)
3) MAX_PAIRS 上限:跨 bidder 总命中超限时按 hit_strength 倒序截断
"""

from __future__ import annotations

import logging
from itertools import combinations

import imagehash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_image import DocumentImage
from app.services.detect.agents.image_impl.config import ImageReuseConfig
from app.services.detect.agents.image_impl.models import (
    DetectionResult,
    MD5Match,
    PHashMatch,
)

logger = logging.getLogger(__name__)

_PHASH_BITS = 64  # phash 是 64 bit


async def _load_images_per_bidder(
    session: AsyncSession,
    project_id: int,
    cfg: ImageReuseConfig,
) -> dict[int, list[tuple[int, int, str, str, str | None]]]:
    """加载项目下所有 bidder 的图片(过滤小图)。

    返 {bidder_id: [(image_id, doc_id, md5, phash, position), ...], ...}。
    """
    stmt = (
        select(
            BidDocument.bidder_id,
            DocumentImage.id,
            DocumentImage.bid_document_id,
            DocumentImage.md5,
            DocumentImage.phash,
            DocumentImage.position,
        )
        .select_from(DocumentImage)
        .join(BidDocument, DocumentImage.bid_document_id == BidDocument.id)
        .join(Bidder, BidDocument.bidder_id == Bidder.id)
        .where(
            Bidder.project_id == project_id,
            Bidder.deleted_at.is_(None),
            DocumentImage.width.is_not(None),
            DocumentImage.height.is_not(None),
            DocumentImage.width >= cfg.min_width,
            DocumentImage.height >= cfg.min_height,
        )
    )
    rows = (await session.execute(stmt)).all()
    grouped: dict[int, list[tuple[int, int, str, str, str | None]]] = {}
    for bidder_id, img_id, doc_id, md5, phash, position in rows:
        grouped.setdefault(bidder_id, []).append(
            (img_id, doc_id, md5, phash, position)
        )
    return grouped


def _hamming(phash_a: str, phash_b: str) -> int:
    """两个 16-char hex 串的 Hamming distance(用 imagehash.hex_to_hash 比较)。

    imagehash.__sub__ 返 numpy int64,显式 cast 到 Python int 避免 JSON 序列化失败。
    """
    a = imagehash.hex_to_hash(phash_a)
    b = imagehash.hex_to_hash(phash_b)
    return int(a - b)


def _compare_pair(
    bidder_a_id: int,
    bidder_b_id: int,
    imgs_a: list[tuple[int, int, str, str, str | None]],
    imgs_b: list[tuple[int, int, str, str, str | None]],
    cfg: ImageReuseConfig,
) -> tuple[list[MD5Match], list[PHashMatch]]:
    """单 pair 比较。返 (md5_matches, phash_matches)。

    去重契约:同对 (img_a_id, img_b_id) 在 MD5 命中后不再进 pHash 路。
    """
    md5_matches: list[MD5Match] = []
    phash_matches: list[PHashMatch] = []

    # MD5 命中的 (img_a, img_b) 对集合
    md5_hit_pairs: set[tuple[int, int]] = set()
    md5_b_index: dict[str, list[tuple[int, int, str, str | None]]] = {}
    for img_id, doc_id, md5, phash, position in imgs_b:
        md5_b_index.setdefault(md5, []).append(
            (img_id, doc_id, phash, position)
        )

    for img_a_id, doc_a_id, md5_a, _phash_a, pos_a in imgs_a:
        for img_b_id, doc_b_id, _phash_b, pos_b in md5_b_index.get(md5_a, []):
            md5_hit_pairs.add((img_a_id, img_b_id))
            md5_matches.append(
                MD5Match(
                    md5=md5_a,
                    doc_id_a=doc_a_id,
                    doc_id_b=doc_b_id,
                    bidder_a_id=bidder_a_id,
                    bidder_b_id=bidder_b_id,
                    position_a=pos_a,
                    position_b=pos_b,
                    hit_strength=1.0,
                    match_type="byte_match",
                )
            )

    # pHash 比较(MD5 未命中的对)
    for img_a_id, doc_a_id, _md5_a, phash_a, pos_a in imgs_a:
        for img_b_id, doc_b_id, _md5_b, phash_b, pos_b in imgs_b:
            if (img_a_id, img_b_id) in md5_hit_pairs:
                continue
            try:
                d = _hamming(phash_a, phash_b)
            except Exception as e:  # noqa: BLE001
                logger.debug("phash compare failed: %s", e)
                continue
            if d <= cfg.phash_distance_threshold:
                phash_matches.append(
                    PHashMatch(
                        phash_a=phash_a,
                        phash_b=phash_b,
                        distance=d,
                        hit_strength=round(1.0 - d / _PHASH_BITS, 4),
                        doc_id_a=doc_a_id,
                        doc_id_b=doc_b_id,
                        bidder_a_id=bidder_a_id,
                        bidder_b_id=bidder_b_id,
                        position_a=pos_a,
                        position_b=pos_b,
                        match_type="visual_similar",
                    )
                )
    return md5_matches, phash_matches


async def compare(
    session: AsyncSession, project_id: int, cfg: ImageReuseConfig
) -> DetectionResult:
    """跨 bidder 两两比较图片。返 DetectionResult。"""
    grouped = await _load_images_per_bidder(session, project_id, cfg)
    bidder_ids = sorted(grouped.keys())

    md5_all: list[MD5Match] = []
    phash_all: list[PHashMatch] = []
    for a, b in combinations(bidder_ids, 2):
        m, p = _compare_pair(a, b, grouped[a], grouped[b], cfg)
        md5_all.extend(m)
        phash_all.extend(p)

    original = len(md5_all) + len(phash_all)
    truncated = False
    if original > cfg.max_pairs:
        # 合并 + 排序 + 截断,优先保留 hit_strength 高的
        all_hits: list[tuple[float, str, dict]] = []
        for m in md5_all:
            all_hits.append((m["hit_strength"], "md5", m))  # type: ignore[arg-type]
        for p in phash_all:
            all_hits.append((p["hit_strength"], "phash", p))  # type: ignore[arg-type]
        all_hits.sort(key=lambda x: x[0], reverse=True)
        kept = all_hits[: cfg.max_pairs]
        md5_all = [h[2] for h in kept if h[1] == "md5"]  # type: ignore[misc]
        phash_all = [h[2] for h in kept if h[1] == "phash"]  # type: ignore[misc]
        truncated = True

    return DetectionResult(
        md5_matches=md5_all,
        phash_matches=phash_all,
        truncated=truncated,
        original_count=original,
    )


__all__ = ["compare"]
