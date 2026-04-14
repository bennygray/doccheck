"""C9 回填脚本:给已上传的 xlsx BidDocument 补写 DocumentSheet。

幂等:已有 DocumentSheet 的 bid_document_id 跳过(NOT EXISTS 子查询)。
错误隔离:单 doc 失败 rollback + 日志,继续下一个。

运行方式(backend 目录):
    uv run python -m scripts.backfill_document_sheets
    uv run python -m scripts.backfill_document_sheets --dry-run   # 只扫不写
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from sqlalchemy import and_, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.document_sheet import DocumentSheet
from app.services.parser.content.xlsx_parser import extract_xlsx

logger = logging.getLogger("backfill_document_sheets")


def _get_max_rows() -> int:
    raw = os.environ.get("STRUCTURE_SIM_MAX_ROWS_PER_SHEET", "").strip()
    if not raw:
        return 5000
    try:
        v = int(raw)
        return v if v > 0 else 5000
    except ValueError:
        return 5000


async def _iter_targets(session: AsyncSession) -> list[BidDocument]:
    """筛选 xlsx + identified + 无 DocumentSheet 的 doc。"""
    subq = (
        select(DocumentSheet.bid_document_id)
        .where(DocumentSheet.bid_document_id == BidDocument.id)
        .exists()
    )
    q = select(BidDocument).where(
        and_(
            BidDocument.file_type == ".xlsx",
            BidDocument.parse_status == "identified",
            not_(subq),
        )
    )
    return (await session.execute(q)).scalars().all()


async def _backfill_one(doc: BidDocument, max_rows: int) -> int:
    """单 doc 独立 session + 独立 commit,失败 rollback 不影响其他。

    返回该 doc 写入的 sheet 数(失败时抛异常给上层 caller 处理)。
    """
    # 独立 session 隔离事务边界
    async with async_session() as s:
        try:
            result = await asyncio.to_thread(extract_xlsx, doc.file_path)
        except Exception as e:
            raise RuntimeError(f"extract_xlsx failed: {e!s}") from e

        count = 0
        for i, sheet in enumerate(result.sheets):
            rows = sheet.rows
            if len(rows) > max_rows:
                logger.warning(
                    "doc=%d sheet %r truncated %d→%d",
                    doc.id,
                    sheet.sheet_name,
                    len(rows),
                    max_rows,
                )
                rows = rows[:max_rows]
            s.add(
                DocumentSheet(
                    bid_document_id=doc.id,
                    sheet_index=i,
                    sheet_name=sheet.sheet_name,
                    hidden=sheet.hidden,
                    rows_json=rows,
                    merged_cells_json=list(sheet.merged_cells_ranges),
                )
            )
            count += 1
        await s.commit()
        return count


async def main(dry_run: bool = False) -> tuple[int, int, int]:
    """扫 + 回填。返回 (total, success, failed)。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    max_rows = _get_max_rows()

    # 先扫一次目标列表(独立 session,避免长事务)
    async with async_session() as s:
        targets = await _iter_targets(s)
    total = len(targets)
    if dry_run:
        logger.info("[DRY-RUN] 扫描到 %d 个 xlsx doc 待回填", total)
        for doc in targets:
            logger.info("  doc=%d file=%s", doc.id, doc.file_name)
        return total, 0, 0

    success = 0
    failed = 0
    for doc in targets:
        try:
            n = await _backfill_one(doc, max_rows)
            success += 1
            logger.info("OK doc=%d sheets=%d", doc.id, n)
        except Exception as e:
            failed += 1
            logger.error("FAIL doc=%d: %s", doc.id, e)

    logger.info(
        "backfill done: total=%d success=%d failed=%d", total, success, failed
    )
    return total, success, failed


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="C9 DocumentSheet backfill for existing xlsx BidDocuments."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只扫目标不写入(列出 doc 数和每个 doc 文件名)",
    )
    args = parser.parse_args()
    total, success, failed = asyncio.run(main(dry_run=args.dry_run))
    # 非 0 退出:有失败 → 1
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    cli()
