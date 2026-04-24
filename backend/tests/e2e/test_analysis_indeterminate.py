"""L2 - analysis 全链路产出 indeterminate 报告
(honest-detection-results F2 + F2 的 ironclad-overrides 子场景)

3 个 case:
(a) 所有信号型 agent succeeded 但 score=0 + 无铁证 → report.risk_level=indeterminate
(b) 1 个信号型 agent score=20 其余 0 → risk_level != indeterminate
(c) agent score 全 0 但 PC.is_ironclad=True → 铁证短路走 LLM 路径,不 indeterminate

统一 patch call_llm_judge 以统计调用次数 + 避免真 LLM。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.bidder import Bidder
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.models.user import User
from app.services.detect import judge_llm
from app.services.detect.judge import judge_and_create_report

pytestmark = pytest.mark.asyncio


async def _seed(
    tag: str,
    *,
    signal_agents_zero: bool = True,
    one_signal_score: float | None = None,
    pc_is_ironclad: bool = False,
) -> tuple[int, int]:
    """seed 一个 project + 2 bidder + 一批 AgentTask(覆盖信号型/非信号型 agent)。

    signal_agents_zero=True → 6 个 signal + 4 个 metadata/price succeeded 全零
    one_signal_score=20 → 把 text_similarity 的 score 改成 20
    pc_is_ironclad=True → 额外插 1 行 pc.is_ironclad=True
    """
    async with async_session() as s:
        user = User(
            username=f"rc_ind_{tag}",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        s.add(user)
        await s.flush()
        project = Project(name=f"P_{tag}", owner_id=user.id, status="analyzing")
        s.add(project)
        await s.flush()
        ba = Bidder(name=f"A_{tag}", project_id=project.id, parse_status="extracted")
        bb = Bidder(name=f"B_{tag}", project_id=project.id, parse_status="extracted")
        s.add(ba)
        s.add(bb)
        await s.flush()

        signal_agents = [
            "text_similarity", "section_similarity", "structure_similarity",
            "image_reuse", "style", "error_consistency",
        ]
        nonsignal_agents = [
            "metadata_author", "metadata_time", "metadata_machine",
            "price_consistency",
        ]

        def _tscore(agent_name: str) -> Decimal:
            if one_signal_score is not None and agent_name == "text_similarity":
                return Decimal(str(one_signal_score))
            return Decimal("0")

        for an in signal_agents:
            s.add(
                AgentTask(
                    project_id=project.id,
                    version=1,
                    agent_name=an,
                    agent_type="pair" if an.startswith(("text_", "section_", "structure_")) else "global",
                    pair_bidder_a_id=ba.id if an.startswith(("text_", "section_", "structure_")) else None,
                    pair_bidder_b_id=bb.id if an.startswith(("text_", "section_", "structure_")) else None,
                    status="succeeded",
                    score=_tscore(an),
                )
            )
        for an in nonsignal_agents:
            s.add(
                AgentTask(
                    project_id=project.id,
                    version=1,
                    agent_name=an,
                    agent_type="pair",
                    pair_bidder_a_id=ba.id,
                    pair_bidder_b_id=bb.id,
                    status="succeeded",
                    score=Decimal("0"),
                )
            )

        if pc_is_ironclad:
            s.add(
                PairComparison(
                    project_id=project.id,
                    version=1,
                    bidder_a_id=ba.id,
                    bidder_b_id=bb.id,
                    dimension="metadata_author",
                    score=Decimal("100"),
                    evidence_json={},
                    is_ironclad=True,
                )
            )
        if one_signal_score is not None:
            s.add(
                PairComparison(
                    project_id=project.id,
                    version=1,
                    bidder_a_id=ba.id,
                    bidder_b_id=bb.id,
                    dimension="text_similarity",
                    score=Decimal(str(one_signal_score)),
                    evidence_json={},
                    is_ironclad=False,
                )
            )

        await s.commit()
        return project.id, 1


async def _cleanup(tag_prefix: str = "rc_ind_") -> None:
    from sqlalchemy import delete, select

    async with async_session() as s:
        user_ids = (
            await s.execute(
                select(User.id).where(User.username.like(f"{tag_prefix}%"))
            )
        ).scalars().all()
        if not user_ids:
            return
        project_ids = (
            await s.execute(
                select(Project.id).where(Project.owner_id.in_(user_ids))
            )
        ).scalars().all()
        if project_ids:
            await s.execute(
                delete(AnalysisReport).where(
                    AnalysisReport.project_id.in_(project_ids)
                )
            )
            await s.execute(
                delete(OverallAnalysis).where(
                    OverallAnalysis.project_id.in_(project_ids)
                )
            )
            await s.execute(
                delete(PairComparison).where(
                    PairComparison.project_id.in_(project_ids)
                )
            )
            await s.execute(
                delete(AgentTask).where(AgentTask.project_id.in_(project_ids))
            )
            await s.execute(delete(Bidder).where(Bidder.project_id.in_(project_ids)))
            await s.execute(delete(Project).where(Project.id.in_(project_ids)))
        await s.execute(delete(User).where(User.id.in_(user_ids)))
        await s.commit()


@pytest.fixture
async def clean_indet():
    await _cleanup()
    yield
    await _cleanup()


async def test_all_signal_zero_produces_indeterminate(
    clean_indet, monkeypatch
) -> None:
    """(a) 信号型 agent 全零 → indeterminate + LLM 不被调"""
    pid, version = await _seed("allzero")

    call_count = {"n": 0}

    async def _counting(*args, **kwargs):
        call_count["n"] += 1
        return "should-not-be-called", 50.0

    monkeypatch.setattr(judge_llm, "call_llm_judge", _counting)

    await judge_and_create_report(pid, version)

    from sqlalchemy import select
    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()
    assert report.risk_level == "indeterminate"
    assert "证据不足" in report.llm_conclusion
    assert call_count["n"] == 0  # LLM 未被调


async def test_mixed_signal_walks_llm_not_indeterminate(
    clean_indet, monkeypatch
) -> None:
    """(b) 1 信号型 agent 非零 → 走 LLM 路径,不触发 indeterminate"""
    pid, version = await _seed("mixed", one_signal_score=20)

    async def _ok(*args, **kwargs):
        return "LLM 正常研判结论", 30.0

    monkeypatch.setattr(judge_llm, "call_llm_judge", _ok)

    await judge_and_create_report(pid, version)

    from sqlalchemy import select
    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()
    assert report.risk_level != "indeterminate"
    assert report.llm_conclusion == "LLM 正常研判结论"


async def test_ironclad_short_circuits_indeterminate(
    clean_indet, monkeypatch
) -> None:
    """(c) score 全零但 PC.is_ironclad=True → 走 LLM 路径(铁证短路)"""
    pid, version = await _seed("ironclad", pc_is_ironclad=True)

    call_count = {"n": 0}

    async def _ok(*args, **kwargs):
        call_count["n"] += 1
        return "发现铁证", 90.0

    monkeypatch.setattr(judge_llm, "call_llm_judge", _ok)

    await judge_and_create_report(pid, version)

    from sqlalchemy import select
    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()
    # 铁证触发公式升级到 ≥85 → high 档
    assert report.risk_level == "high"
    assert report.risk_level != "indeterminate"
    assert call_count["n"] == 1  # LLM 被调
