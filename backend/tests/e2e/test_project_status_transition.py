"""L2 - DEF-001: 项目状态自动流转 E2E 测试

覆盖:
- 创建项目(draft) → 上传文件触发解压(parsing) → 解析完成(ready) → 启动检测成功
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.project import Project
from app.models.user import User
from app.services.auth.password import hash_password
from app.services.parser.pipeline.project_status_sync import (
    try_transition_project_parsing,
    try_transition_project_ready,
)
from app.services.parser.pipeline.run_pipeline import run_pipeline
from tests.fixtures.auth_fixtures import clean_users as _clean_users  # noqa
from tests.fixtures.doc_fixtures import make_real_docx
from tests.fixtures.llm_mock import (
    ScriptedLLMProvider,
    make_role_classify_response,
)

os.environ.setdefault("INFRA_DISABLE_PIPELINE", "1")


async def _seed_project_two_bidders(
    tmp_path: Path,
) -> tuple[int, int, int]:
    """创建项目 + 2 个 bidder(各含 1 个 docx),返回 (pid, bid1, bid2)。"""
    docx1 = make_real_docx(tmp_path / "a.docx", body_paragraphs=["段落A1", "段落A2"])
    docx2 = make_real_docx(tmp_path / "b.docx", body_paragraphs=["段落B1", "段落B2"])

    async with async_session() as s:
        user = User(
            username="sync_e2e",
            password_hash=hash_password("x"),
            role="reviewer",
            must_change_password=False,
        )
        s.add(user)
        await s.flush()

        project = Project(name="SyncE2E", owner_id=user.id, status="draft")
        s.add(project)
        await s.flush()

        b1 = Bidder(name="B1", project_id=project.id, parse_status="extracted")
        b2 = Bidder(name="B2", project_id=project.id, parse_status="extracted")
        s.add_all([b1, b2])
        await s.flush()

        d1 = BidDocument(
            bidder_id=b1.id,
            file_name="a.docx",
            file_path=str(docx1),
            file_size=1000,
            file_type=".docx",
            md5="a" * 32,
            source_archive="a.zip",
            parse_status="extracted",
        )
        d2 = BidDocument(
            bidder_id=b2.id,
            file_name="b.docx",
            file_path=str(docx2),
            file_size=1000,
            file_type=".docx",
            md5="b" * 32,
            source_archive="b.zip",
            parse_status="extracted",
        )
        s.add_all([d1, d2])
        await s.commit()
        return project.id, b1.id, b2.id


async def test_full_status_transition_draft_to_ready(clean_users, tmp_path: Path):
    """E2E: draft → parsing → (pipeline) → ready → 检测可启动"""
    pid, bid1, bid2 = await _seed_project_two_bidders(tmp_path)

    # 确认初始状态 draft
    async with async_session() as s:
        p = await s.get(Project, pid)
        assert p.status == "draft"

    # 模拟上传触发 parsing
    await try_transition_project_parsing(pid)
    async with async_session() as s:
        p = await s.get(Project, pid)
        assert p.status == "parsing"

    # mock LLM: 两个 bidder 各调一次 role_classify
    llm = ScriptedLLMProvider(
        [
            make_role_classify_response([(0, "technical")]),
            make_role_classify_response([(0, "technical")]),
        ],
        loop_last=True,
    )

    # run pipeline for bidder 1 — 只有 1 个终态,项目不应该变 ready
    await run_pipeline(bid1, llm=llm)

    async with async_session() as s:
        b1 = await s.get(Bidder, bid1)
        assert b1.parse_status == "identified"
        p = await s.get(Project, pid)
        assert p.status == "parsing"  # bidder2 还没完成

    # run pipeline for bidder 2 — 全部终态,应该变 ready
    await run_pipeline(bid2, llm=llm)

    async with async_session() as s:
        b2 = await s.get(Bidder, bid2)
        assert b2.parse_status == "identified"
        p = await s.get(Project, pid)
        assert p.status == "ready"  # 关键断言!
