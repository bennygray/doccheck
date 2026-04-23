"""L1 - role_classifier N3 observability 日志契约 (llm-classifier-observability)。

验证 3 条诊断日志 + raw_text_head 扩展 + mojibake helper 的行为:
- input shape (info) 总被记录
- output confidence mix (info) 仅 LLM 成功路径记录
- invalid JSON warning 含 raw_text_head 且截到 200 字符
- _looks_mojibake heuristic 正反 case
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_image import DocumentImage
from app.models.document_metadata import DocumentMetadata
from app.models.document_sheet import DocumentSheet
from app.models.document_text import DocumentText
from app.models.project import Project
from app.models.user import User
from app.services.llm.base import LLMError, LLMResult, Message
from app.services.parser.llm.role_classifier import (
    _looks_mojibake,
    classify_bidder,
)


OBS_LOGGER = "app.services.parser.llm.role_classifier"


@dataclass
class FakeLLM:
    """可配置返回值的 mock LLM。"""

    name: str = "fake"
    text: str = ""
    error: LLMError | None = None
    calls: int = 0
    last_messages: list[Message] = field(default_factory=list)

    async def complete(self, messages: list[Message], **kw) -> LLMResult:
        self.calls += 1
        self.last_messages = list(messages)
        return LLMResult(text=self.text, error=self.error)


async def _seed(
    session: AsyncSession, docs: list[dict], tag: str
) -> tuple[int, list[int]]:
    user = User(
        username=f"rc_obs_{tag}_{id(session)}",
        password_hash="x",
        role="reviewer",
        login_fail_count=0,
    )
    session.add(user)
    await session.flush()
    project = Project(name=f"P_{tag}", owner_id=user.id)
    session.add(project)
    await session.flush()
    bidder = Bidder(
        name=f"B_{tag}", project_id=project.id, parse_status="extracted"
    )
    session.add(bidder)
    await session.flush()
    doc_ids: list[int] = []
    for i, spec in enumerate(docs):
        bd = BidDocument(
            bidder_id=bidder.id,
            file_name=spec["name"],
            file_path=f"/tmp/obs_{tag}_{i}",
            file_size=100,
            file_type=spec.get("type", ".docx"),
            md5=(f"obs{tag[:3]}{i:02d}" + "x" * 30)[:32],
            source_archive="a.zip",
            parse_status=spec.get("parse_status", "identified"),
        )
        session.add(bd)
        await session.flush()
        doc_ids.append(bd.id)
        first_text = spec.get("first_text")
        if first_text:
            session.add(
                DocumentText(
                    bid_document_id=bd.id,
                    paragraph_index=0,
                    text=first_text,
                    location="body",
                )
            )
    await session.commit()
    return bidder.id, doc_ids


@pytest_asyncio.fixture
async def clean_obs_data():
    prefix = "rc_obs_"

    async def _purge():
        async with async_session() as session:
            user_ids = (
                await session.execute(
                    select(User.id).where(User.username.like(f"{prefix}%"))
                )
            ).scalars().all()
            if not user_ids:
                return
            project_ids = (
                await session.execute(
                    select(Project.id).where(Project.owner_id.in_(user_ids))
                )
            ).scalars().all()
            bidder_ids = (
                (
                    await session.execute(
                        select(Bidder.id).where(
                            Bidder.project_id.in_(project_ids)
                        )
                    )
                ).scalars().all()
                if project_ids
                else []
            )
            doc_ids = (
                (
                    await session.execute(
                        select(BidDocument.id).where(
                            BidDocument.bidder_id.in_(bidder_ids)
                        )
                    )
                ).scalars().all()
                if bidder_ids
                else []
            )
            if doc_ids:
                for table in (
                    DocumentText,
                    DocumentMetadata,
                    DocumentImage,
                    DocumentSheet,
                ):
                    await session.execute(
                        delete(table).where(
                            table.bid_document_id.in_(doc_ids)
                        )
                    )
                await session.execute(
                    delete(BidDocument).where(BidDocument.id.in_(doc_ids))
                )
            if bidder_ids:
                await session.execute(
                    delete(Bidder).where(Bidder.id.in_(bidder_ids))
                )
            if project_ids:
                await session.execute(
                    delete(Project).where(Project.id.in_(project_ids))
                )
            await session.execute(
                delete(User).where(User.id.in_(user_ids))
            )
            await session.commit()

    await _purge()
    yield
    await _purge()


def _input_records(caplog) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records
        if r.name == OBS_LOGGER
        and r.levelno == logging.INFO
        and r.getMessage().startswith("role_classifier input ")
    ]


def _output_records(caplog) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records
        if r.name == OBS_LOGGER
        and r.levelno == logging.INFO
        and r.getMessage().startswith("role_classifier output ")
    ]


def _warning_records(caplog) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records
        if r.name == OBS_LOGGER and r.levelno == logging.WARNING
    ]


@pytest.mark.asyncio
async def test_input_shape_logged_with_all_fields(clean_obs_data, caplog):
    """LLM 成功路径:input shape info 含全部 4 字段。"""
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    async with async_session() as session:
        bidder_id, doc_ids = await _seed(
            session,
            [
                {"name": "tech.docx", "first_text": "技术方案概述"},
                {"name": "price.xlsx", "type": ".xlsx", "first_text": "报价清单"},
            ],
            tag="in_shape",
        )
    llm = FakeLLM(
        text=json.dumps(
            {
                "roles": [
                    {"document_id": doc_ids[0], "role": "technical", "confidence": "high"},
                    {"document_id": doc_ids[1], "role": "pricing", "confidence": "high"},
                ]
            }
        )
    )
    async with async_session() as session:
        await classify_bidder(session, bidder_id, llm)

    recs = _input_records(caplog)
    assert len(recs) == 1, f"expected 1 input shape log, got {len(recs)}"
    msg = recs[0].getMessage()
    assert "files=2" in msg
    assert "snippet_empty=0" in msg
    assert "total_prompt_chars=" in msg
    # 有具体数字
    assert any(
        part.startswith("total_prompt_chars=") and int(part.split("=", 1)[1]) > 0
        for part in msg.split()
    )
    assert "file_name_has_mojibake=False" in msg


@pytest.mark.asyncio
async def test_output_mix_logged_on_success(clean_obs_data, caplog):
    """LLM 成功且含混合 confidence:output mix 记录 high/low/missing 准确,总和=文档数。"""
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    async with async_session() as session:
        bidder_id, doc_ids = await _seed(
            session,
            [
                {"name": "a.docx", "first_text": "aa"},
                {"name": "b.docx", "first_text": "bb"},
                {"name": "c.docx", "first_text": "cc"},
            ],
            tag="out_mix",
        )
    # LLM 返:doc[0] high,doc[1] low,doc[2] 漏返
    llm = FakeLLM(
        text=json.dumps(
            {
                "roles": [
                    {"document_id": doc_ids[0], "role": "technical", "confidence": "high"},
                    {"document_id": doc_ids[1], "role": "pricing", "confidence": "low"},
                ]
            }
        )
    )
    async with async_session() as session:
        await classify_bidder(session, bidder_id, llm)

    recs = _output_records(caplog)
    assert len(recs) == 1
    msg = recs[0].getMessage()
    assert "llm_confidence_high=1" in msg
    assert "low=1" in msg
    assert "missing=1" in msg


@pytest.mark.asyncio
async def test_output_mix_not_logged_on_llm_error(clean_obs_data, caplog):
    """LLM error 路径:input shape 记录 + kind warning 记录,但不记 output mix。"""
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    async with async_session() as session:
        bidder_id, _ = await _seed(
            session,
            [{"name": "x.docx", "first_text": "xx"}],
            tag="err_path",
        )
    llm = FakeLLM(error=LLMError(kind="timeout", message="boom"))
    async with async_session() as session:
        await classify_bidder(session, bidder_id, llm)

    assert len(_input_records(caplog)) == 1
    assert len(_output_records(caplog)) == 0, "output mix MUST NOT fire on LLM error"
    warn_msgs = [r.getMessage() for r in _warning_records(caplog)]
    assert any("kind=timeout" in m for m in warn_msgs)


@pytest.mark.asyncio
async def test_invalid_json_warning_includes_raw_head_short(
    clean_obs_data, caplog
):
    """非法 JSON 短串:warning 含 raw_text_head= + 完整原文。"""
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    async with async_session() as session:
        bidder_id, _ = await _seed(
            session,
            [{"name": "x.docx", "first_text": "xx"}],
            tag="bad_json_short",
        )
    bad = '{"roles":[{"doc'
    llm = FakeLLM(text=bad)
    async with async_session() as session:
        await classify_bidder(session, bidder_id, llm)

    warns = [r.getMessage() for r in _warning_records(caplog)]
    assert any(
        "returned invalid JSON" in m and "raw_text_head=" in m and bad in m
        for m in warns
    ), warns
    # output mix 不应触发
    assert len(_output_records(caplog)) == 0


@pytest.mark.asyncio
async def test_invalid_json_warning_truncates_to_200_chars(
    clean_obs_data, caplog
):
    """非法 JSON 长串(>200):raw_text_head 按 code point 截到 200。"""
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    async with async_session() as session:
        bidder_id, _ = await _seed(
            session,
            [{"name": "x.docx", "first_text": "xx"}],
            tag="bad_json_long",
        )
    # 300 个中文字符,非法 JSON
    long_bad = "投" * 300
    llm = FakeLLM(text=long_bad)
    async with async_session() as session:
        await classify_bidder(session, bidder_id, llm)

    warns = [r.getMessage() for r in _warning_records(caplog)]
    matched = [m for m in warns if "raw_text_head=" in m]
    assert matched, warns
    msg = matched[0]
    # repr('投' * 200) 嵌入消息;确认 200 个"投"在消息里,201 个不在
    assert ("投" * 200) in msg
    assert ("投" * 201) not in msg


@pytest.mark.parametrize(
    "name,expected",
    [
        ("", False),
        ("tech.docx", False),
        ("投标文件.docx", False),
        ("._投标文件.docx", False),  # 纯 ASCII + UTF-8 中文,不含 mojibake 片段
        ("._µ▒ƒΦïÅµèòµáçµûçΣ╗╢.docx", True),  # 典型 cp850-GBK mojibake
        ("abc Θöéµ║É.txt", True),  # 含 Θö 片段
    ],
)
def test_looks_mojibake_heuristic(name: str, expected: bool):
    assert _looks_mojibake(name) is expected
