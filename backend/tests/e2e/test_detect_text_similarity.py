"""L2 - text_similarity Agent 真实双轨链路 (C7)

场景覆盖(execution-plan §3 C7 5 个):
1. 抄袭样本高分 + is_ironclad
2. 独立样本低分 + 无铁证
3. LLM 降级(timeout)→ degraded=true + status=succeeded
4. 超短文档 → AgentTask.status=skipped
5. 三份中一对命中 → 仅 (A,B) 高分

策略:
- 构造 2 bidder 的技术方案 DocumentText(抄袭 / 独立)
- monkeypatch `app.services.llm.get_llm_provider` 注入 ScriptedLLMProvider
- 不启动 project.analyzing 流程,直接跑 text_similarity Agent 的 run()(更快更稳)
- 其余 9 Agent 的 dummy 不参与此测试
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_text import DocumentText
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.models.user import User
from app.services.detect.agents import text_similarity as ts_mod
from app.services.detect.context import AgentContext
from tests.fixtures.llm_mock import (
    ScriptedLLMProvider,
    make_text_similarity_response,
)

pytestmark = pytest.mark.asyncio


# ---------- seed helpers ----------

_TECH_A = (
    "本项目采用先进的人工智能技术方案,通过自然语言处理和机器学习算法,"
    "实现对投标文件的自动化分析和围标行为识别。"
    "系统具备高并发处理能力,支持多投标人并行检测。"
)
# text-sim-exact-match-bypass:抄袭测试用"近似抄袭"(改 1 字),避开 hash 旁路命中,
# 仍走 cosine + LLM judge 路径(原"一字不改"设置会被 hash 旁路截走不调 LLM)
_TECH_B_COPY = _TECH_A.replace("人工智能技术方案", "人工智慧技术方案")
_TECH_B_INDEPENDENT = (
    "饮食搭配应当均衡,多吃蔬菜水果,富含维生素和膳食纤维,"
    "有助于身体健康。早睡早起有益于身心调节,保持心情愉悦。"
    "运动锻炼需要持之以恒,方能收到良好效果。"
)


async def _seed_project_and_bidders(
    owner_id: int,
    bidder_texts: list[list[str]],
) -> tuple[int, list[int]]:
    """建 project + N bidder,每 bidder 一份技术方案 BidDocument + DocumentText 段落。

    bidder_texts[i] 是 bidder i 的段落列表(每段字符 ≥ 200 才能撑过 500 MIN)。
    """
    async with async_session() as s:
        p = Project(name="c7-test", status="ready", owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)

        bidder_ids: list[int] = []
        for i, paras in enumerate(bidder_texts):
            b = Bidder(
                name=f"B{i}", project_id=p.id, parse_status="identified"
            )
            s.add(b)
            await s.flush()
            doc = BidDocument(
                bidder_id=b.id,
                file_name=f"tech-{i}.docx",
                file_path=f"/tmp/{i}.docx",
                file_size=1000,
                file_type=".docx",
                md5=f"m{i}" * 8,
                file_role="technical",
                parse_status="content_parsed",
                source_archive=f"a{i}.zip",
            )
            s.add(doc)
            await s.flush()
            for idx, text in enumerate(paras):
                s.add(
                    DocumentText(
                        bid_document_id=doc.id,
                        paragraph_index=idx,
                        text=text,
                        location="body",
                    )
                )
            bidder_ids.append(b.id)
        await s.commit()
        return p.id, bidder_ids


async def _make_agent_task(
    project_id: int, a_id: int, b_id: int, version: int = 1
) -> int:
    """插 AgentTask 行,返 id。"""
    async with async_session() as s:
        task = AgentTask(
            project_id=project_id,
            version=version,
            agent_name="text_similarity",
            agent_type="pair",
            pair_bidder_a_id=a_id,
            pair_bidder_b_id=b_id,
            status="pending",
        )
        s.add(task)
        await s.commit()
        await s.refresh(task)
        return task.id


async def _load_pair_comparison(
    project_id: int, a_id: int, b_id: int
) -> PairComparison | None:
    async with async_session() as s:
        stmt = select(PairComparison).where(
            PairComparison.project_id == project_id,
            PairComparison.bidder_a_id == a_id,
            PairComparison.bidder_b_id == b_id,
            PairComparison.dimension == "text_similarity",
        )
        return (await s.execute(stmt)).scalar_one_or_none()


async def _run_text_similarity(
    project_id: int, a_id: int, b_id: int, llm_provider
) -> AgentContext:
    """手动构造 ctx 调 run(),返 ctx(内含结果),绕开 engine 的 track/超时逻辑。"""
    task_id = await _make_agent_task(project_id, a_id, b_id)
    async with async_session() as s:
        task = await s.get(AgentTask, task_id)
        a = await s.get(Bidder, a_id)
        b = await s.get(Bidder, b_id)
        ctx = AgentContext(
            project_id=project_id,
            version=1,
            agent_task=task,
            bidder_a=a,
            bidder_b=b,
            all_bidders=[],
            llm_provider=llm_provider,
            session=s,
        )
        await ts_mod.run(ctx)
        await s.commit()
        return ctx


# ---------- Scenario 1: 抄袭命中 ----------

async def test_text_similarity_plagiarism_hit(clean_users, seeded_reviewer: User):
    paras_a = [_TECH_A * 2]  # 超过 500 字符
    paras_b = [_TECH_B_COPY * 2]
    pid, bids = await _seed_project_and_bidders(seeded_reviewer.id, [paras_a, paras_b])

    llm = ScriptedLLMProvider(
        [make_text_similarity_response(
            [(i, "plagiarism") for i in range(30)],
            overall="整体抄袭",
            confidence="high",
        )],
        loop_last=True,
    )
    await _run_text_similarity(pid, bids[0], bids[1], llm)

    pc = await _load_pair_comparison(pid, bids[0], bids[1])
    assert pc is not None
    assert float(pc.score) >= 60.0
    assert pc.is_ironclad is True
    assert pc.evidence_json["algorithm"] == "tfidf_cosine_v1"
    assert pc.evidence_json["degraded"] is False
    assert pc.evidence_json["pairs_plagiarism"] >= 1


# ---------- Scenario 2: 独立不误报 ----------

async def test_text_similarity_independent_no_false_positive(
    clean_users, seeded_reviewer: User
):
    paras_a = [_TECH_A * 2]
    paras_b = [_TECH_B_INDEPENDENT * 2]
    pid, bids = await _seed_project_and_bidders(seeded_reviewer.id, [paras_a, paras_b])

    # 给 LLM 一个意外调用的 timeout 信号(若被调则降级;但预期 pairs_total=0 根本不会调)
    llm = ScriptedLLMProvider([make_text_similarity_response([])], loop_last=True)
    await _run_text_similarity(pid, bids[0], bids[1], llm)

    pc = await _load_pair_comparison(pid, bids[0], bids[1])
    assert pc is not None
    assert float(pc.score) < 30.0
    assert pc.is_ironclad is False
    # 独立样本:TF-IDF 筛选应筛不出 sim >= 0.70 的段对
    assert pc.evidence_json["pairs_total"] == 0


# ---------- Scenario 3: LLM 降级 ----------

async def test_text_similarity_llm_timeout_degrades(
    clean_users, seeded_reviewer: User
):
    from app.services.llm.base import LLMError

    paras_a = [_TECH_A * 2]
    paras_b = [_TECH_B_COPY * 2]
    pid, bids = await _seed_project_and_bidders(seeded_reviewer.id, [paras_a, paras_b])

    llm = ScriptedLLMProvider(
        [LLMError(kind="timeout", message="t")], loop_last=True
    )
    await _run_text_similarity(pid, bids[0], bids[1], llm)

    pc = await _load_pair_comparison(pid, bids[0], bids[1])
    assert pc is not None
    assert pc.evidence_json["degraded"] is True
    assert pc.evidence_json["ai_judgment"] is None
    assert pc.is_ironclad is False  # 降级不触发铁证


# ---------- Scenario 4: 超短文档 skip ----------

async def test_text_similarity_too_short_preflight_skips(
    clean_users, seeded_reviewer: User
):
    # 两侧都 < 500 字符
    paras_a = ["短文本"]
    paras_b = ["也短"]
    pid, bids = await _seed_project_and_bidders(seeded_reviewer.id, [paras_a, paras_b])

    # preflight 应返 skip;不调 run
    async with async_session() as s:
        a = await s.get(Bidder, bids[0])
        b = await s.get(Bidder, bids[1])
        task = AgentTask(
            project_id=pid, version=1, agent_name="text_similarity",
            agent_type="pair", pair_bidder_a_id=a.id, pair_bidder_b_id=b.id,
            status="pending",
        )
        s.add(task)
        await s.flush()
        ctx = AgentContext(
            project_id=pid, version=1, agent_task=task,
            bidder_a=a, bidder_b=b, all_bidders=[],
            llm_provider=None, session=s,
        )
        pf = await ts_mod.preflight(ctx)
        assert pf.status == "skip"
        assert "文档过短" in (pf.reason or "")


# ---------- Scenario 5: 三份中一对命中 ----------

async def test_text_similarity_three_bidders_one_pair_hit(
    clean_users, seeded_reviewer: User
):
    """3 bidder:A 和 B 抄袭,C 独立。仅 (A,B) 高分 + 铁证。"""
    paras_a = [_TECH_A * 2]
    paras_b = [_TECH_B_COPY * 2]
    paras_c = [_TECH_B_INDEPENDENT * 2]
    pid, bids = await _seed_project_and_bidders(
        seeded_reviewer.id, [paras_a, paras_b, paras_c]
    )

    # (A,B) 给 plagiarism;(A,C) / (B,C) LLM 不会被调用(pairs_total=0 即可)
    llm = ScriptedLLMProvider(
        [make_text_similarity_response(
            [(i, "plagiarism") for i in range(30)],
            overall="A-B 抄袭",
            confidence="high",
        )],
        loop_last=True,
    )

    await _run_text_similarity(pid, bids[0], bids[1], llm)
    await _run_text_similarity(pid, bids[0], bids[2], llm)
    await _run_text_similarity(pid, bids[1], bids[2], llm)

    pc_ab = await _load_pair_comparison(pid, bids[0], bids[1])
    pc_ac = await _load_pair_comparison(pid, bids[0], bids[2])
    pc_bc = await _load_pair_comparison(pid, bids[1], bids[2])

    assert pc_ab is not None and pc_ac is not None and pc_bc is not None
    assert float(pc_ab.score) >= 60.0
    assert pc_ab.is_ironclad is True
    assert float(pc_ac.score) < 30.0
    assert pc_ac.is_ironclad is False
    assert float(pc_bc.score) < 30.0
    assert pc_bc.is_ironclad is False
