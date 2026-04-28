"""per-bidder 解析流水线主协程 (C5 parser-pipeline)

阶段:
1. 内容提取(extract_content per doc)
2. LLM 角色分类 + 身份信息(classify_bidder)
3. 若有 pricing XLSX:acquire_or_wait_rule → fill_price per doc
4. 聚合 bidder.parse_status

失败隔离:各阶段 try/except,失败只标该阶段态,不阻塞同项目其他 bidder。
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.services.llm.base import LLMProvider
from app.services.llm.factory import get_llm_provider
from app.services.parser.content import extract_content
from app.services.parser.llm.role_classifier import classify_bidder
from app.services.parser.pipeline.fill_price import fill_price_from_rule
from app.services.parser.pipeline.progress_broker import progress_broker
from app.services.parser.pipeline.project_status_sync import try_transition_project_ready
from app.services.parser.pipeline.rule_coordinator import acquire_or_wait_rule
from app.services.parser.pipeline.sheet_role_validator import validate_sheet_roles

logger = logging.getLogger(__name__)


async def run_pipeline(
    bidder_id: int, llm: LLMProvider | None = None
) -> None:
    """主入口。协程内部 new session,不复用外部。"""
    llm = llm or get_llm_provider()

    # --- 阶段 1: 内容提取 + 状态转 identifying ---
    project_id = await _get_project_id(bidder_id)
    if project_id is None:
        return

    await _publish_status(bidder_id, project_id, "identifying")

    try:
        await _phase_extract_content(bidder_id)
    except Exception as e:
        logger.exception("pipeline phase1 failed bidder=%d", bidder_id)
        await _set_bidder_failed(
            bidder_id, "identify_failed", f"内容提取异常: {e!s}"[:500]
        )
        await _publish_status(bidder_id, project_id, "identify_failed")
        await _safe_try_transition(project_id)
        return

    # --- 阶段 2: LLM 角色分类 + 身份信息 ---
    try:
        async with async_session() as session:
            await classify_bidder(session, bidder_id, llm)
        # classify 后广播文档角色事件
        async with async_session() as session:
            stmt = (
                select(BidDocument)
                .where(BidDocument.bidder_id == bidder_id)
                .where(BidDocument.file_type.in_([".docx", ".xlsx"]))
            )
            docs = (await session.execute(stmt)).scalars().all()
            for d in docs:
                await progress_broker.publish(
                    project_id,
                    "document_role_classified",
                    {
                        "document_id": d.id,
                        "bidder_id": bidder_id,
                        "role": d.file_role,
                        "confidence": d.role_confidence,
                    },
                )
    except Exception as e:
        logger.exception("pipeline phase2 failed bidder=%d", bidder_id)
        await _set_bidder_failed(
            bidder_id, "identify_failed", f"LLM 分类异常: {e!s}"[:500]
        )
        await _publish_status(bidder_id, project_id, "identify_failed")
        await _safe_try_transition(project_id)
        return

    # 检查是否 identify_failed(内容提取全失败)
    if await _should_stop_after_identify(bidder_id):
        async with async_session() as session:
            bidder = await session.get(Bidder, bidder_id)
            if bidder is not None:
                bidder.parse_status = "identify_failed"
                await session.commit()
        await _publish_status(bidder_id, project_id, "identify_failed")
        await _safe_try_transition(project_id)
        return

    # 正常进 identified
    async with async_session() as session:
        bidder = await session.get(Bidder, bidder_id)
        if bidder is not None:
            bidder.parse_status = "identified"
            bidder.parse_error = None
            await session.commit()
    await _publish_status(bidder_id, project_id, "identified")

    # --- 阶段 3: 报价阶段(仅当有 pricing XLSX) ---
    pricing_xlsx = await _find_pricing_xlsx(bidder_id)
    if not pricing_xlsx:
        # 无报价表 → identified 即终态
        await _safe_try_transition(project_id)
        return

    await _set_bidder_status(bidder_id, "pricing")
    await _publish_status(bidder_id, project_id, "pricing")

    try:
        rule = await acquire_or_wait_rule(project_id, pricing_xlsx, llm)
    except Exception as e:
        logger.exception("rule coord raised bidder=%d", bidder_id)
        rule = None

    if rule is None:
        await _set_bidder_failed(
            bidder_id, "price_failed", "报价规则识别失败,可 re-parse 重试或手工配置"
        )
        await _publish_status(bidder_id, project_id, "price_failed")
        await progress_broker.publish(
            project_id,
            "error",
            {"bidder_id": bidder_id, "stage": "price_rule", "message": "rule识别失败"},
        )
        await _safe_try_transition(project_id)
        return

    # 首发协程应推 project_price_rule_ready(仅 confirmed 后推;多次推也幂等但节省流量)
    await progress_broker.publish(
        project_id,
        "project_price_rule_ready",
        {
            "rule_id": rule.id,
            "confirmed": True,
            "sheet_name": rule.sheet_name,
            "header_row": rule.header_row,
        },
    )

    # 回填(可能多个 pricing xlsx)
    all_pricing = await _find_all_pricing_xlsx(bidder_id)
    total_items = 0
    succeeded: list[str] = []
    failed: list[str] = []
    for path in all_pricing:
        try:
            async with async_session() as session:
                r = await fill_price_from_rule(session, bidder_id, rule, path)
                total_items += r.items_count
                succeeded.extend(r.succeeded_sheets)
                failed.extend(r.partial_failed_sheets)
        except Exception as e:
            logger.exception("fill_price failed bidder=%d path=%s", bidder_id, path)
            failed.append(str(Path(path).name))

    # fix-multi-sheet-price-double-count F:数值兜底校验 sheet_role
    # 若 LLM 误判(都标 main 但 SUM 相等),根据行数纠正
    # 修正 → UPDATE rule.sheets_config + 写 audit_log
    try:
        await _run_sheet_role_validator(bidder_id, rule.id)
    except Exception:
        logger.exception(
            "sheet_role validator failed bidder=%d rule=%d (non-fatal)",
            bidder_id, rule.id,
        )

    # 终态判定 (β 方案)
    if succeeded and not failed:
        final_status = "priced"
        parse_error = None
    elif succeeded and failed:
        final_status = "price_partial"
        parse_error = f"部分 sheet 失败: {', '.join(failed)}"[:500]
    else:
        final_status = "price_failed"
        parse_error = f"所有 sheet 回填失败: {', '.join(failed)}"[:500] if failed else "无有效报价数据"

    await _set_bidder_terminal(bidder_id, final_status, parse_error)
    await _publish_status(bidder_id, project_id, final_status)
    await progress_broker.publish(
        project_id,
        "bidder_price_filled",
        {
            "bidder_id": bidder_id,
            "items_count": total_items,
            "partial_failed_sheets": failed,
        },
    )
    await _safe_try_transition(project_id)


async def _safe_try_transition(project_id: int) -> None:
    """调用 try_transition_project_ready,捕获异常防止 fire-and-forget task 静默崩溃。"""
    try:
        await try_transition_project_ready(project_id)
    except Exception:
        logger.exception(
            "try_transition_project_ready failed for project=%d", project_id
        )


async def _phase_extract_content(bidder_id: int) -> None:
    """对 bidder 下所有 extracted 文档逐个调 extract_content。

    只处理 .docx / .xlsx 这两类业务文档;跳过归档行(.zip/.7z/.rar)与图片
    等其他 file_type — 归档行自身不是可解析内容,若进来会被 extract_content
    误标成 skipped + '未知文件类型 .zip',同时**覆盖** extract 阶段写入的
    审计 parse_error(如 '已过滤 N 个打包垃圾文件')
    (fix-mac-packed-zip-parsing 端到端修复)。
    """
    async with async_session() as session:
        stmt = select(BidDocument).where(
            BidDocument.bidder_id == bidder_id,
            BidDocument.file_type.in_([".docx", ".xlsx"]),
            BidDocument.parse_status.in_(["extracted", "identify_failed"]),
        )
        docs = (await session.execute(stmt)).scalars().all()
        doc_ids = [d.id for d in docs]

    for doc_id in doc_ids:
        async with async_session() as session:
            await extract_content(session, doc_id)


async def _get_project_id(bidder_id: int) -> int | None:
    async with async_session() as session:
        bidder = await session.get(Bidder, bidder_id)
        return bidder.project_id if bidder is not None else None


async def _should_stop_after_identify(bidder_id: int) -> bool:
    """所有 DOCX/XLSX 都 identify_failed → 整 bidder 进 identify_failed。"""
    async with async_session() as session:
        stmt = select(BidDocument).where(
            BidDocument.bidder_id == bidder_id,
            BidDocument.file_type.in_([".docx", ".xlsx"]),
        )
        docs = (await session.execute(stmt)).scalars().all()
        if not docs:
            return True
        return all(d.parse_status == "identify_failed" for d in docs)


async def _find_pricing_xlsx(bidder_id: int) -> str | None:
    """首个 pricing/unit_price 角色的 XLSX,用于 rule 识别(胜出者喂 LLM 的样本)。

    fix-unit-price-orphan-fallback:按 role 优先级顺序选取,**单 bidder 单类不变量**:
    - 先找 ``file_role='pricing'``,有则返回首个
    - 没有再找 ``file_role='unit_price'`` (fallback,兜底 LLM 误判)
    - 都没有返 None
    与 ``_find_all_pricing_xlsx`` 必须保持对称(同一 bidder 选出相同 role)。
    详见 spec ``parser-pipeline`` ADDED Requirement
    "报价 XLSX 选取 fallback 与单 bidder 单类不变量"。
    """
    async with async_session() as session:
        for role in ("pricing", "unit_price"):
            stmt = (
                select(BidDocument)
                .where(BidDocument.bidder_id == bidder_id)
                .where(BidDocument.file_role == role)
                .where(BidDocument.file_type == ".xlsx")
                .where(BidDocument.parse_status == "identified")
                .limit(1)
            )
            doc = (await session.execute(stmt)).scalar_one_or_none()
            if doc is not None:
                return doc.file_path
        return None


async def _find_all_pricing_xlsx(bidder_id: int) -> list[str]:
    """所有 pricing/unit_price 角色的 XLSX,用于报价回填遍历。

    fix-unit-price-orphan-fallback:按 role 优先级顺序选取,**单 bidder 单类不变量**:
    - 先找 ``file_role='pricing'``,有则返回所有 pricing 类(不混合 unit_price)
    - 没有再找 ``file_role='unit_price'`` (fallback)
    - 都没有返 []
    返回的列表内部 **永不混合** 两类 role,保护下游 ``aggregate_bidder_totals``
    不被"主表+子单价表混算"污染(避免 ``price_overshoot`` /
    ``price_total_match`` 等铁证级 detector 误算)。
    与 ``_find_pricing_xlsx`` 必须保持对称(同一 bidder 选出相同 role)。
    详见 spec ``parser-pipeline`` ADDED Requirement。
    """
    async with async_session() as session:
        for role in ("pricing", "unit_price"):
            stmt = (
                select(BidDocument)
                .where(BidDocument.bidder_id == bidder_id)
                .where(BidDocument.file_role == role)
                .where(BidDocument.file_type == ".xlsx")
                .where(BidDocument.parse_status == "identified")
            )
            docs = (await session.execute(stmt)).scalars().all()
            if docs:
                return [d.file_path for d in docs]
        return []


async def _run_sheet_role_validator(bidder_id: int, rule_id: int) -> None:
    """fix-multi-sheet-price-double-count F:数值兜底校验 sheet_role。

    在某 bidder 报价回填完成后调用,根据该 bidder 的 price_items 行数+SUM 关系,
    检查 LLM 给的 sheet_role 是否合理;若发现"两 sheet SUM 相等但都标 main",
    根据行数纠正(行少为 main, 行多为 breakdown);UPDATE rule.sheets_config。
    决策记录在 logger.warning(audit log 字段不匹配自动场景,本 change 不动 schema)。
    """
    from app.models.price_item import PriceItem
    from app.models.price_parsing_rule import PriceParsingRule
    from sqlalchemy.orm.attributes import flag_modified

    async with async_session() as session:
        rule = await session.get(PriceParsingRule, rule_id)
        if rule is None or not rule.sheets_config:
            return

        items = (
            await session.execute(
                select(PriceItem).where(PriceItem.bidder_id == bidder_id)
            )
        ).scalars().all()
        if not items:
            return

        original = list(rule.sheets_config)
        fixed, decisions = validate_sheet_roles(original, items)
        if not decisions:
            return

        rule.sheets_config = fixed
        # JSONB 列改 list 内部时 SQLAlchemy 不知道,显式 flag_modified
        flag_modified(rule, "sheets_config")
        await session.commit()
        logger.info(
            "sheet_role validator applied %d fix(es) on rule=%d bidder=%d: %s",
            len(decisions), rule_id, bidder_id, "; ".join(decisions),
        )


async def _set_bidder_status(bidder_id: int, status: str) -> None:
    async with async_session() as session:
        bidder = await session.get(Bidder, bidder_id)
        if bidder is not None:
            bidder.parse_status = status
            await session.commit()


async def _set_bidder_failed(
    bidder_id: int, status: str, msg: str
) -> None:
    async with async_session() as session:
        bidder = await session.get(Bidder, bidder_id)
        if bidder is not None:
            bidder.parse_status = status
            bidder.parse_error = msg
            await session.commit()


async def _set_bidder_terminal(
    bidder_id: int, status: str, parse_error: str | None
) -> None:
    async with async_session() as session:
        bidder = await session.get(Bidder, bidder_id)
        if bidder is not None:
            bidder.parse_status = status
            bidder.parse_error = parse_error
            await session.commit()


async def _publish_status(
    bidder_id: int, project_id: int, new_status: str
) -> None:
    await progress_broker.publish(
        project_id,
        "bidder_status_changed",
        {"bidder_id": bidder_id, "new_status": new_status},
    )


__all__ = ["run_pipeline"]
