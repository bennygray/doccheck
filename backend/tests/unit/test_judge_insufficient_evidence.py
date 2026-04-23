"""L1 - judge 证据不足判定 (honest-detection-results D1 / F2)

覆盖:
- _has_sufficient_evidence 纯函数的 6 种输入组合
- judge_and_create_report 在证据不足场景下产出 indeterminate report + 不调 LLM
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

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


# ---------------------------------------------- 纯函数 _has_sufficient_evidence


@dataclass
class _T:
    """AgentTask 的轻量 stub(只需 status / agent_name / score 3 个字段)"""
    status: str
    agent_name: str
    score: float | None = None


@dataclass
class _PC:
    is_ironclad: bool = False


@dataclass
class _OA:
    evidence_json: dict | None = None


def test_all_skipped_returns_false() -> None:
    tasks = [
        _T("skipped", "text_similarity"),
        _T("skipped", "section_similarity"),
    ]
    assert judge_llm._has_sufficient_evidence(tasks, [], []) is False


def test_all_signal_agents_zero_returns_false() -> None:
    tasks = [
        _T("succeeded", "text_similarity", 0),
        _T("succeeded", "section_similarity", 0),
        _T("succeeded", "image_reuse", 0),
    ]
    assert judge_llm._has_sufficient_evidence(tasks, [], []) is False


def test_signal_agent_nonzero_returns_true() -> None:
    tasks = [
        _T("succeeded", "text_similarity", 24.5),
        _T("succeeded", "section_similarity", 0),
    ]
    assert judge_llm._has_sufficient_evidence(tasks, [], []) is True


def test_only_metadata_nonzero_still_insufficient() -> None:
    """关键场景:metadata_author 发现碰撞(score=50)但信号型 agent 全零
    → 按白名单定义 metadata_* 不算信号型 → 证据不足"""
    tasks = [
        _T("succeeded", "metadata_author", 50),
        _T("succeeded", "text_similarity", 0),
        _T("succeeded", "section_similarity", 0),
        _T("succeeded", "image_reuse", 0),
        _T("succeeded", "style", 0),
        _T("succeeded", "error_consistency", 0),
    ]
    assert judge_llm._has_sufficient_evidence(tasks, [], []) is False


def test_ironclad_via_pair_comparison_short_circuits() -> None:
    """铁证场景:agent.score 全零但 PC.is_ironclad=True → 短路返 True"""
    tasks = [
        _T("succeeded", "text_similarity", 0),
        _T("succeeded", "image_reuse", 0),
    ]
    pcs = [_PC(is_ironclad=True)]
    assert judge_llm._has_sufficient_evidence(tasks, pcs, []) is True


def test_ironclad_via_overall_analysis_short_circuits() -> None:
    tasks = [_T("succeeded", "text_similarity", 0)]
    oas = [_OA(evidence_json={"has_iron_evidence": True})]
    assert judge_llm._has_sufficient_evidence(tasks, [], oas) is True


def test_all_failed_no_ironclad_returns_false() -> None:
    tasks = [
        _T("failed", "text_similarity"),
        _T("timeout", "image_reuse"),
    ]
    assert judge_llm._has_sufficient_evidence(tasks, [], []) is False


def test_empty_inputs_return_false() -> None:
    assert judge_llm._has_sufficient_evidence([], [], []) is False
    assert judge_llm._has_sufficient_evidence(None, None, None) is False


# ---------------------------------------------- judge_and_create_report 集成


@pytest_asyncio.fixture
async def clean_judge_ie_data():
    prefix = "rc_jie_"

    async def _purge():
        async with async_session() as s:
            user_ids = (
                await s.execute(
                    select(User.id).where(User.username.like(f"{prefix}%"))
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
                    delete(AgentTask).where(
                        AgentTask.project_id.in_(project_ids)
                    )
                )
                await s.execute(
                    delete(Bidder).where(Bidder.project_id.in_(project_ids))
                )
                await s.execute(
                    delete(Project).where(Project.id.in_(project_ids))
                )
            await s.execute(delete(User).where(User.id.in_(user_ids)))
            await s.commit()

    await _purge()
    yield
    await _purge()


async def _seed_project_with_tasks(
    tag: str, agent_specs: list[dict[str, Any]]
) -> tuple[int, int, int, int]:
    """返 (project_id, version=1, bidder_a_id, bidder_b_id)"""
    async with async_session() as s:
        user = User(
            username=f"rc_jie_{tag}",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        s.add(user)
        await s.flush()
        project = Project(name=f"P_{tag}", owner_id=user.id, status="analyzing")
        s.add(project)
        await s.flush()
        bidder_a = Bidder(
            name=f"B1_{tag}", project_id=project.id, parse_status="extracted"
        )
        bidder_b = Bidder(
            name=f"B2_{tag}", project_id=project.id, parse_status="extracted"
        )
        s.add(bidder_a)
        s.add(bidder_b)
        await s.flush()
        for spec in agent_specs:
            agent_type = spec.get("agent_type", "pair")
            s.add(
                AgentTask(
                    project_id=project.id,
                    version=1,
                    agent_name=spec["agent_name"],
                    agent_type=agent_type,
                    # pair 类需要两个 bidder id,global 类需为 None
                    pair_bidder_a_id=bidder_a.id if agent_type == "pair" else None,
                    pair_bidder_b_id=bidder_b.id if agent_type == "pair" else None,
                    status=spec["status"],
                    score=(
                        Decimal(str(spec["score"]))
                        if spec.get("score") is not None
                        else None
                    ),
                )
            )
        await s.commit()
        return project.id, 1, bidder_a.id, bidder_b.id


@pytest.mark.asyncio
async def test_judge_all_zero_signal_produces_indeterminate(
    clean_judge_ie_data, monkeypatch
) -> None:
    pid, version, _, _ = await _seed_project_with_tasks(
        "allzero",
        [
            {"agent_name": "text_similarity", "status": "succeeded", "score": 0},
            {"agent_name": "section_similarity", "status": "succeeded", "score": 0},
            {"agent_name": "image_reuse", "status": "succeeded", "score": 0, "agent_type": "global"},
            {"agent_name": "style", "status": "succeeded", "score": 0, "agent_type": "global"},
            {"agent_name": "error_consistency", "status": "succeeded", "score": 0, "agent_type": "global"},
        ],
    )

    # mock LLM — 如果被调用就抛异常,断言 LLM 未被调
    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("LLM should not be called when evidence is insufficient")

    monkeypatch.setattr(judge_llm, "call_llm_judge", _fail_if_called)

    await judge_and_create_report(pid, version)

    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()
    assert report.risk_level == "indeterminate"
    assert "证据不足" in report.llm_conclusion
    assert "无法判定" in report.llm_conclusion


@pytest.mark.asyncio
async def test_judge_signal_nonzero_walks_llm_path(
    clean_judge_ie_data, monkeypatch
) -> None:
    pid, version, bid_a, bid_b = await _seed_project_with_tasks(
        "nonzero",
        [
            {"agent_name": "text_similarity", "status": "succeeded", "score": 20},
        ],
    )

    # mock LLM 成功
    llm_call_count = {"n": 0}

    async def _ok_llm(summary, formula_total, *, provider=None, cfg=None):
        llm_call_count["n"] += 1
        return ("LLM 综合研判 OK", 30.0)

    monkeypatch.setattr(judge_llm, "call_llm_judge", _ok_llm)

    # 需要 pair_comparison 让 text_similarity 进 per_dim_max
    async with async_session() as s:
        s.add(
            PairComparison(
                project_id=pid,
                version=version,
                bidder_a_id=bid_a,
                bidder_b_id=bid_b,
                dimension="text_similarity",
                score=Decimal("20"),
                evidence_json={},
                is_ironclad=False,
            )
        )
        await s.commit()

    await judge_and_create_report(pid, version)

    assert llm_call_count["n"] >= 1  # LLM 被调

    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()
    assert report.risk_level != "indeterminate"
    assert report.llm_conclusion == "LLM 综合研判 OK"
