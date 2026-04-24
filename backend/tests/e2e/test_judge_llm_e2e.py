"""L2: judge_and_create_report 端到端 (C14 detect-llm-judge)

4 scenario:
- S1 LLM 成功升分跨档(formula=65 medium → LLM=75 → high)
- S2 LLM 试图降铁证被守护(formula=88+iron → LLM=60 → 守护 final=88)
- S3 LLM 失败走降级兜底(llm_conclusion 前缀标语 + 模板)
- S4 LLM_JUDGE_ENABLED=false 跳过 LLM 直接走降级

不走 engine 全流水;直接调 judge.judge_and_create_report + 预 seed PC/OA。
这样隔离检测 11 Agent 侧的复杂性,专测 C14 judge 层。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.bidder import Bidder
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.models.user import User
from app.services.detect import judge, judge_llm

pytestmark = pytest.mark.asyncio


async def _seed_project_with_bidders(owner_id: int, n: int = 3) -> int:
    async with async_session() as s:
        p = Project(name="p-c14", status="analyzing", owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        for i in range(n):
            s.add(
                Bidder(
                    name=f"B{i}",
                    project_id=p.id,
                    parse_status="identified",
                )
            )
        await s.commit()
        return p.id


async def _seed_pcs(
    project_id: int,
    rows: list[tuple[str, float, bool]],
) -> None:
    """rows: [(dimension, score, is_ironclad)]"""
    async with async_session() as s:
        # 拿 bidder ids
        bidders = (
            await s.execute(
                select(Bidder).where(Bidder.project_id == project_id)
            )
        ).scalars().all()
        if len(bidders) < 2:
            raise RuntimeError("seed bidders first")
        for dim, score, iron in rows:
            s.add(
                PairComparison(
                    project_id=project_id,
                    version=1,
                    bidder_a_id=bidders[0].id,
                    bidder_b_id=bidders[1].id,
                    dimension=dim,
                    score=Decimal(str(score)),
                    is_ironclad=iron,
                    evidence_json={},
                )
            )
        await s.commit()


async def _seed_oas(
    project_id: int,
    rows: list[tuple[str, float, dict | None]],
) -> None:
    """rows: [(dimension, score, evidence_json_or_None)]"""
    async with async_session() as s:
        for dim, score, ev in rows:
            s.add(
                OverallAnalysis(
                    project_id=project_id,
                    version=1,
                    dimension=dim,
                    score=Decimal(str(score)),
                    evidence_json=ev or {},
                )
            )
        await s.commit()


async def _seed_agent_tasks_succeeded(
    project_id: int, agent_names: list[str]
) -> None:
    """为 honest-detection-results 的 `_has_sufficient_evidence` 提供信号。

    该函数断言"至少一个 SIGNAL_AGENTS agent 以 succeeded + score>0 状态存在",
    否则 judge 直接走 `INSUFFICIENT_EVIDENCE_CONCLUSION` 而非 `FALLBACK_PREFIX`。
    老 L2 测试在 dev DB 下因残留 AgentTask 行巧合通过;clean testdb(N5)暴露出
    显式 seed AgentTask 的必要(harden-async-infra 观察)。

    对 pair 型 agent 设 bidder_a/b(满足 check constraint
    `ck_agent_tasks_pair_bidder_consistency`);error_consistency 是 global 型,
    两侧 NULL。
    """
    async with async_session() as s:
        bidders = (
            await s.execute(
                select(Bidder).where(Bidder.project_id == project_id)
            )
        ).scalars().all()
        if len(bidders) < 2:
            raise RuntimeError("seed bidders first")
        for name in agent_names:
            is_global = name == "error_consistency"
            s.add(
                AgentTask(
                    project_id=project_id,
                    version=1,
                    agent_name=name,
                    agent_type="global" if is_global else "pair",
                    status="succeeded",
                    score=Decimal("50"),
                    pair_bidder_a_id=None if is_global else bidders[0].id,
                    pair_bidder_b_id=None if is_global else bidders[1].id,
                )
            )
        await s.commit()


async def _get_report(project_id: int) -> AnalysisReport | None:
    async with async_session() as s:
        return (
            await s.execute(
                select(AnalysisReport).where(
                    AnalysisReport.project_id == project_id,
                    AnalysisReport.version == 1,
                )
            )
        ).scalar_one_or_none()


# ============================================================ S1: upgrade


async def test_s1_llm_upgrade_crosses_tier(
    seeded_reviewer: User, monkeypatch
):
    """formula=65 medium + 无铁证 + LLM 建议 75 → final=75 high"""
    pid = await _seed_project_with_bidders(seeded_reviewer.id, n=3)
    # 凑 formula_total ≈ 65:
    # text_sim 0.12 * 100 + section_sim 0.10 * 100 + error_consistency 0.12 * 100
    # + metadata_author 0.10 * 100 + metadata_machine 0.10 * 100 + price_consistency 0.10 * 100
    # = 12+10+12+10+10+10 = 64
    await _seed_pcs(
        pid,
        [
            ("text_similarity", 100, False),
            ("section_similarity", 100, False),
            ("metadata_author", 100, False),
            ("metadata_machine", 100, False),
            ("price_consistency", 100, False),
        ],
    )
    await _seed_oas(pid, [("error_consistency", 100, None)])
    # harden-async-infra N5:clean testdb 暴露需显式 seed AgentTask 满足
    # honest-detection-results 的 `_has_sufficient_evidence` SIGNAL_AGENTS 检查
    await _seed_agent_tasks_succeeded(
        pid,
        ["text_similarity", "section_similarity", "error_consistency"],
    )

    # mock LLM 返 suggested=75(override e2e conftest autouse 的 (None,None))
    async def _llm_upgrade(summary, formula_total, *, provider=None, cfg=None):
        return "综合研判:跨维度共振,建议升分。", 75.0

    monkeypatch.setattr(judge_llm, "call_llm_judge", _llm_upgrade)

    await judge.judge_and_create_report(pid, version=1)

    report = await _get_report(pid)
    assert report is not None
    assert float(report.total_score) == 75.0
    assert report.risk_level == "high"
    assert "综合研判" in report.llm_conclusion
    assert judge_llm.FALLBACK_PREFIX not in report.llm_conclusion


# ========================================================= S2: ironclad guard


async def test_s2_llm_tries_lower_ironclad_guarded(
    seeded_reviewer: User, monkeypatch
):
    """formula=88 + 铁证 + LLM 建议 60 → final=88(守护成功)"""
    pid = await _seed_project_with_bidders(seeded_reviewer.id, n=3)
    # 注:铁证命中触发 compute_formula_total 硬升到 ≥85,故即便原加权为 12
    # 铁证会拉到 85。加一个额外 pc 让 formula_total ≈ 88:
    # text_sim 100 * 0.12 = 12 + 铁证升 85,但我们要 88 → 给更多分
    # error_consistency 100 * 0.12 = 12 + text_sim 100 * 0.12 = 12 + 铁证 85 → 24 vs 85 取 85
    # 想得 88,需 formula 无铁证时 > 85;再叠铁证守护
    # 直接给多维度凑到 88:
    # text 12 + section 10 + error 12 + meta_author 10 + meta_time 8 + meta_machine 10
    # + price_consist 10 + price_anom 7 + style 8 + image 5 + struct 8 = 100
    # 各取 88% → 大致 88
    score = 88.0
    await _seed_pcs(
        pid,
        [
            ("text_similarity", score, False),
            ("section_similarity", score, False),
            ("structure_similarity", score, False),
            ("metadata_author", score, False),
            ("metadata_time", score, False),
            ("metadata_machine", score, False),
            ("price_consistency", score, True),  # 铁证
        ],
    )
    await _seed_oas(
        pid,
        [
            ("error_consistency", score, None),
            ("style", score, None),
            ("image_reuse", score, None),
            ("price_anomaly", score, None),
        ],
    )

    async def _llm_low(summary, formula_total, *, provider=None, cfg=None):
        return "LLM 试图降分测试", 60.0

    monkeypatch.setattr(judge_llm, "call_llm_judge", _llm_low)

    await judge.judge_and_create_report(pid, version=1)

    report = await _get_report(pid)
    assert report is not None
    # 铁证守护:final ≥ 85;max(formula≈88, 60) = 88 ≥ 85 → final=88
    assert float(report.total_score) >= 85.0
    assert float(report.total_score) >= 87.0  # 贴近 formula=88
    assert report.risk_level == "high"
    # llm_conclusion 来自 LLM(升分失败但 LLM 成功),非降级前缀
    assert judge_llm.FALLBACK_PREFIX not in report.llm_conclusion


# ============================================================== S3: failed


async def test_s3_llm_failed_goes_to_fallback(
    seeded_reviewer: User, monkeypatch
):
    """LLM 失败(autouse fixture 已默认 patch 返 (None,None))→ 降级模板"""
    pid = await _seed_project_with_bidders(seeded_reviewer.id, n=3)
    await _seed_pcs(
        pid,
        [
            ("text_similarity", 80, False),
            ("price_consistency", 60, False),
        ],
    )
    await _seed_oas(pid, [("error_consistency", 90, None)])
    await _seed_agent_tasks_succeeded(
        pid, ["text_similarity", "error_consistency"]
    )

    # autouse _disable_l9_llm_by_default 已 patch,直接跑即走降级
    await judge.judge_and_create_report(pid, version=1)

    report = await _get_report(pid)
    assert report is not None
    assert report.llm_conclusion.startswith(judge_llm.FALLBACK_PREFIX)
    # 降级态 total = formula(不受 LLM 影响)
    # formula = 0.12*80 + 0.10*60 + 0.12*90 = 9.6 + 6 + 10.8 = 26.4 → low
    assert report.risk_level == "low"
    assert float(report.total_score) < 40.0
    # 模板必须含若干关键字
    assert "综合研判暂不可用" in report.llm_conclusion
    assert "总分" in report.llm_conclusion
    assert "风险等级" in report.llm_conclusion


# ============================================================ S4: disabled


async def test_s4_env_disabled_skips_llm(
    seeded_reviewer: User, monkeypatch
):
    """LLM_JUDGE_ENABLED=false → 不调 LLM 直接走降级"""
    monkeypatch.setenv("LLM_JUDGE_ENABLED", "false")
    # 额外显式让 call_llm_judge 爆炸,验证根本不被调
    call_count = {"n": 0}

    async def _should_not_be_called(*a, **kw):
        call_count["n"] += 1
        raise AssertionError("call_llm_judge should not be invoked when ENABLED=false")

    monkeypatch.setattr(judge_llm, "call_llm_judge", _should_not_be_called)

    pid = await _seed_project_with_bidders(seeded_reviewer.id, n=2)
    await _seed_pcs(pid, [("text_similarity", 50, False)])
    await _seed_oas(pid, [("error_consistency", 50, None)])
    await _seed_agent_tasks_succeeded(
        pid, ["text_similarity", "error_consistency"]
    )

    await judge.judge_and_create_report(pid, version=1)

    assert call_count["n"] == 0
    report = await _get_report(pid)
    assert report is not None
    assert report.llm_conclusion.startswith(judge_llm.FALLBACK_PREFIX)


# ======================================================== S5: idempotency


async def test_s5_idempotent_skip_if_report_exists(
    seeded_reviewer: User, monkeypatch
):
    """已有 AnalysisReport 行 → 跳过,不覆盖 llm_conclusion"""
    pid = await _seed_project_with_bidders(seeded_reviewer.id, n=2)

    # 手工插一条 pre-existing report
    async with async_session() as s:
        s.add(
            AnalysisReport(
                project_id=pid,
                version=1,
                total_score=Decimal("42.0"),
                risk_level="medium",
                llm_conclusion="pre-existing conclusion",
            )
        )
        await s.commit()

    # 调 judge — 应该幂等 skip
    await judge.judge_and_create_report(pid, version=1)

    report = await _get_report(pid)
    assert report is not None
    assert report.llm_conclusion == "pre-existing conclusion"
    assert float(report.total_score) == 42.0
