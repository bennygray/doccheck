"""L1 - parser/pipeline/rule_coordinator 单元测试 (C5 §9.8)

核心测试 E3 方案:
- 首发 INSERT 成功 → LLM 调用 → UPDATE confirmed
- 冲突 → 走等待路径(event 快路径)
- event 超时 → DB poll 兜底

需要真实 DB(Postgres partial unique index)。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.session import async_session
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project
from app.models.user import User
from app.services.llm.base import LLMError, LLMResult, Message
from app.services.parser.pipeline import rule_coordinator
from app.services.parser.pipeline.rule_coordinator import (
    acquire_or_wait_rule,
    reset_for_tests,
)
from tests.fixtures.doc_fixtures import make_price_xlsx


@dataclass
class FakeLLM:
    name: str = "fake"
    response_text: str = ""
    error: LLMError | None = None

    async def complete(self, messages: list[Message], **kw) -> LLMResult:
        if self.error is not None:
            return LLMResult(text="", error=self.error)
        return LLMResult(text=self.response_text)


@pytest_asyncio.fixture
async def clean_rule_data():
    async with async_session() as session:
        await session.execute(delete(PriceParsingRule).where(PriceParsingRule.id > 0))
        await session.execute(delete(Project).where(Project.id > 0))
        await session.execute(delete(User).where(User.id > 0))
        await session.commit()
    reset_for_tests()
    yield
    reset_for_tests()
    async with async_session() as session:
        await session.execute(delete(PriceParsingRule).where(PriceParsingRule.id > 0))
        await session.execute(delete(Project).where(Project.id > 0))
        await session.execute(delete(User).where(User.id > 0))
        await session.commit()


async def _seed_project() -> int:
    async with async_session() as session:
        user = User(
            username="rc_test",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        session.add(user)
        await session.flush()
        project = Project(name="P", owner_id=user.id)
        session.add(project)
        await session.commit()
        return project.id


@pytest.mark.asyncio
async def test_first_caller_inserts_and_confirms(
    clean_rule_data, tmp_path: Path
) -> None:
    import json

    pid = await _seed_project()
    xlsx = make_price_xlsx(tmp_path / "p.xlsx")
    llm = FakeLLM(
        response_text=json.dumps(
            {
                "sheet_name": "报价清单",
                "header_row": 2,
                "column_mapping": {
                    "code_col": "A",
                    "name_col": "B",
                    "unit_col": "C",
                    "qty_col": "D",
                    "unit_price_col": "E",
                    "total_price_col": "F",
                    "skip_cols": [],
                },
            }
        )
    )
    rule = await acquire_or_wait_rule(pid, xlsx, llm)
    assert rule is not None
    assert rule.status == "confirmed"
    assert rule.confirmed is True


@pytest.mark.asyncio
async def test_llm_failure_returns_none_and_marks_failed(
    clean_rule_data, tmp_path: Path
) -> None:
    pid = await _seed_project()
    xlsx = make_price_xlsx(tmp_path / "p.xlsx")
    llm = FakeLLM(error=LLMError(kind="timeout", message="x"))
    rule = await acquire_or_wait_rule(pid, xlsx, llm)
    assert rule is None

    # DB 中应当留一条 failed 记录
    from sqlalchemy import select
    async with async_session() as session:
        row = (
            await session.execute(
                select(PriceParsingRule).where(PriceParsingRule.project_id == pid)
            )
        ).scalar_one()
        assert row.status == "failed"


@pytest.mark.asyncio
async def test_second_caller_waits_for_first(
    clean_rule_data, tmp_path: Path
) -> None:
    """并发两个 acquire:首发应占位,第二个走等待路径并拿到同一规则。"""
    import json

    pid = await _seed_project()
    xlsx = make_price_xlsx(tmp_path / "p.xlsx")
    response = json.dumps(
        {
            "sheet_name": "报价清单",
            "header_row": 2,
            "column_mapping": {
                "code_col": "A",
                "name_col": "B",
                "unit_col": "C",
                "qty_col": "D",
                "unit_price_col": "E",
                "total_price_col": "F",
                "skip_cols": [],
            },
        }
    )

    # 用 sleep 的 LLM 让第二个 caller 在等待期间到达
    @dataclass
    class SlowLLM:
        name: str = "slow"

        async def complete(self, messages, **kw):
            await asyncio.sleep(0.2)
            return LLMResult(text=response)

    llm1 = SlowLLM()
    llm2 = SlowLLM()

    # 并发两个 acquire
    results = await asyncio.gather(
        acquire_or_wait_rule(pid, xlsx, llm1),
        acquire_or_wait_rule(pid, xlsx, llm2),
    )
    rule1, rule2 = results
    assert rule1 is not None and rule2 is not None
    # 两者应指向同一 DB 行
    assert rule1.id == rule2.id
    assert rule1.status == "confirmed"
