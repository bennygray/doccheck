"""报价规则识别并发控制 (C5 parser-pipeline D3 决策)

E3 方案:DB 原子 INSERT 占位 + asyncio.Event 快路径 + DB poll 慢路径。

- 胜出者(INSERT 成功):调 detect_price_rule → UPDATE status='confirmed'|'failed' + event.set()
- 等待者(INSERT 冲突):先 event.wait(timeout=10s);超时降级 DB poll 每 3s 共 5 分钟
- 进程重启:event 丢失 → 下轮协程进入 poll 路径,5 分钟内读取到 DB 终态仍可用
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.price_parsing_rule import PriceParsingRule
from app.services.llm.base import LLMProvider
from app.services.parser.llm.price_rule_detector import detect_price_rule

logger = logging.getLogger(__name__)

# 进程内 project 级 event(快路径)
_RULE_EVENTS: dict[int, asyncio.Event] = {}

# poll 慢路径参数
_EVENT_TIMEOUT_S = 10.0
_POLL_INTERVAL_S = 3.0
_POLL_TIMEOUT_S = 300.0  # 5 分钟


def _get_event(project_id: int) -> asyncio.Event:
    event = _RULE_EVENTS.get(project_id)
    if event is None:
        event = asyncio.Event()
        _RULE_EVENTS[project_id] = event
    return event


async def acquire_or_wait_rule(
    project_id: int,
    xlsx_path: str | Path,
    llm: LLMProvider,
) -> PriceParsingRule | None:
    """争抢"规则识别胜出者"资格。胜出则调 LLM 识别;失败走等待。

    返回值:
    - 已 confirmed 的 PriceParsingRule(胜出或等到)
    - None:识别失败(status=failed)或超时
    """
    event = _get_event(project_id)

    # 尝试 INSERT 占位
    try:
        async with async_session() as session:
            rule = await _try_claim(session, project_id)
    except IntegrityError:
        rule = None

    if rule is not None:
        # 胜出者路径
        try:
            draft = await detect_price_rule(xlsx_path, llm)
        except Exception as e:  # pragma: no cover - defense in depth
            logger.exception("detect_price_rule raised: %s", e)
            draft = None

        async with async_session() as session:
            row = await session.get(PriceParsingRule, rule.id)
            if row is None:
                event.set()
                return None
            if draft is None:
                row.status = "failed"
                await session.commit()
                event.set()
                _RULE_EVENTS.pop(project_id, None)
                return None
            row.sheet_name = draft.sheet_name
            row.header_row = draft.header_row
            row.column_mapping = draft.column_mapping
            row.status = "confirmed"
            row.confirmed = True
            row.created_by_llm = True
            await session.commit()
            event.set()
            _RULE_EVENTS.pop(project_id, None)
            # 重新加载返回
            return await session.get(PriceParsingRule, rule.id)

    # 等待者路径
    return await _wait_for_rule(project_id, event)


async def _try_claim(
    session: AsyncSession, project_id: int
) -> PriceParsingRule | None:
    """尝试 INSERT 占位 (status='identifying');冲突抛 IntegrityError。

    调用方若捕获 IntegrityError 说明已有人占位,进入等待。
    """
    row = PriceParsingRule(
        project_id=project_id,
        sheet_name="_identifying_",  # 占位
        header_row=1,
        column_mapping={},
        status="identifying",
        created_by_llm=True,
        confirmed=False,
    )
    session.add(row)
    try:
        await session.commit()
        await session.refresh(row)
        return row
    except IntegrityError:
        await session.rollback()
        raise


async def _wait_for_rule(
    project_id: int, event: asyncio.Event
) -> PriceParsingRule | None:
    """先 event.wait(10s) 快路径;超时降级 DB poll 5 分钟。"""
    try:
        await asyncio.wait_for(event.wait(), timeout=_EVENT_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.info(
            "rule_coordinator event timeout project=%d; falling back to poll",
            project_id,
        )

    # event 已 set 或超时 → 查 DB 当前态
    rule = await _load_rule(project_id)
    if rule is not None and rule.status == "confirmed":
        return rule
    if rule is not None and rule.status == "failed":
        return None

    # poll 兜底(进程重启场景)
    deadline_iters = int(_POLL_TIMEOUT_S / _POLL_INTERVAL_S)
    for _ in range(deadline_iters):
        await asyncio.sleep(_POLL_INTERVAL_S)
        rule = await _load_rule(project_id)
        if rule is None:
            continue
        if rule.status == "confirmed":
            return rule
        if rule.status == "failed":
            return None
    # 仍未到达终态 → 放弃
    return None


async def _load_rule(project_id: int) -> PriceParsingRule | None:
    async with async_session() as session:
        stmt = select(PriceParsingRule).where(
            PriceParsingRule.project_id == project_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()


def reset_for_tests() -> None:
    """L2 fixture 用:清内存 event 表,防跨用例串味。"""
    _RULE_EVENTS.clear()


__all__ = ["acquire_or_wait_rule", "reset_for_tests"]
