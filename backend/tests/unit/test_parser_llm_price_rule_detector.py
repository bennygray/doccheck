"""L1 - parser/llm/price_rule_detector 单元测试 (C5 §9.6)"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.services.llm.base import LLMError, LLMResult, Message
from app.services.parser.llm.price_rule_detector import detect_price_rule
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


@pytest.mark.asyncio
async def test_llm_success_returns_rule(tmp_path: Path) -> None:
    xlsx = make_price_xlsx(tmp_path / "p.xlsx", row_count=3)
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
    result = await detect_price_rule(xlsx, llm)
    assert result is not None
    assert result.sheet_name == "报价清单"
    assert result.header_row == 2
    assert result.column_mapping["code_col"] == "A"


@pytest.mark.asyncio
async def test_llm_error_returns_none(tmp_path: Path) -> None:
    xlsx = make_price_xlsx(tmp_path / "p.xlsx")
    llm = FakeLLM(error=LLMError(kind="timeout", message="x"))
    assert await detect_price_rule(xlsx, llm) is None


@pytest.mark.asyncio
async def test_llm_bad_json_returns_none(tmp_path: Path) -> None:
    xlsx = make_price_xlsx(tmp_path / "p.xlsx")
    llm = FakeLLM(response_text="{not-json")
    assert await detect_price_rule(xlsx, llm) is None


@pytest.mark.asyncio
async def test_missing_required_key_returns_none(tmp_path: Path) -> None:
    xlsx = make_price_xlsx(tmp_path / "p.xlsx")
    # 缺 code_col
    llm = FakeLLM(
        response_text=json.dumps(
            {
                "header_row": 2,
                "column_mapping": {
                    "name_col": "B",
                    "unit_col": "C",
                    "qty_col": "D",
                    "unit_price_col": "E",
                    "total_price_col": "F",
                },
            }
        )
    )
    assert await detect_price_rule(xlsx, llm) is None


@pytest.mark.asyncio
async def test_invalid_header_row_returns_none(tmp_path: Path) -> None:
    xlsx = make_price_xlsx(tmp_path / "p.xlsx")
    llm = FakeLLM(
        response_text=json.dumps(
            {
                "header_row": -1,
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
    assert await detect_price_rule(xlsx, llm) is None
