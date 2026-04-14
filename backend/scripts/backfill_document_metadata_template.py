"""C10 回填脚本:给已上传的 docx/xlsx BidDocument 补写 DocumentMetadata.template。

幂等:template 非 NULL 的行跳过(SQL 过滤)。
错误隔离:单 doc 失败 rollback + 日志,继续下一个。
说明:app.xml 缺失 <Template> 节点的文档仍计入 success(写 NULL 保持原值)。

运行方式(backend 目录):
    uv run python -m scripts.backfill_document_metadata_template
    uv run python -m scripts.backfill_document_metadata_template --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.document_metadata import DocumentMetadata
from app.services.parser.content.metadata_parser import extract_metadata

logger = logging.getLogger("backfill_document_metadata_template")


async def _iter_targets(
    session: AsyncSession,
) -> list[tuple[BidDocument, DocumentMetadata]]:
    """筛选 docx/xlsx + identified + template IS NULL 的 (doc, meta) 对。"""
    q = (
        select(BidDocument, DocumentMetadata)
        .join(
            DocumentMetadata,
            DocumentMetadata.bid_document_id == BidDocument.id,
        )
        .where(BidDocument.parse_status == "identified")
        .where(BidDocument.file_type.in_([".docx", ".xlsx"]))
        .where(DocumentMetadata.template.is_(None))
    )
    return (await session.execute(q)).all()


async def _backfill_one(doc: BidDocument) -> str | None:
    """单 doc 独立 session + 独立 commit。返回写入的 template(可能 None)。"""
    async with async_session() as s:
        try:
            meta = await asyncio.to_thread(extract_metadata, doc.file_path)
        except Exception as e:
            raise RuntimeError(f"extract_metadata failed: {e!s}") from e

        row = await s.get(DocumentMetadata, doc.id)
        if row is None:
            # DocumentMetadata 行消失(理论上不会 — 已在目标筛选中 JOIN)
            return None
        row.template = meta.template
        await s.commit()
        return meta.template


async def main(dry_run: bool = False) -> tuple[int, int, int]:
    """扫 + 回填。返回 (total, success, failed)。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    async with async_session() as s:
        targets = await _iter_targets(s)
    total = len(targets)
    if dry_run:
        logger.info(
            "[DRY-RUN] 扫描到 %d 个 doc 待回填 template 字段", total
        )
        for doc, _meta in targets[:5]:
            logger.info("  sample doc=%d file=%s", doc.id, doc.file_name)
        if total > 5:
            logger.info("  ... 以及 %d 条省略", total - 5)
        return total, 0, 0

    success = 0
    failed = 0
    for doc, _meta in targets:
        try:
            tpl = await _backfill_one(doc)
            success += 1
            logger.info("OK doc=%d template=%r", doc.id, tpl)
        except Exception as e:
            failed += 1
            logger.error("FAIL doc=%d: %s", doc.id, e)

    logger.info(
        "backfill done: total=%d success=%d failed=%d",
        total,
        success,
        failed,
    )
    return total, success, failed


def cli() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "C10 DocumentMetadata.template backfill for existing docx/xlsx"
            " BidDocuments."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只扫目标不写入(列出 doc 数和前 5 样例)",
    )
    args = parser.parse_args()
    total, success, failed = asyncio.run(main(dry_run=args.dry_run))
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    cli()
