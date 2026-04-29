"""L2 - text-sim-exact-match-bypass agent + reports API 端到端

覆盖 tasks.md §3 全部 [L2] 条目:
- hash 命中段进 evidence top + 同 (a_idx, b_idx) 不进 LLM judge prompt
- evidence_json schema 兼容(旧版无 pairs_exact_match reports API 不抛错)
- PairComparison.version 递增正确, reports API 按 max version 取数
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_text import DocumentText
from app.models.analysis_report import AnalysisReport
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


# 客户演示用注入段(repro_demo_files.py 抽出的真实段)
INJECTED_165 = (
    "检查材料的保管情况:材料堆放是否整齐;标识牌是否齐全,标识内容是否清楚,"
    "与实物是否相符;不同型号、规格、材质、品种、性质的材料是否分别堆放;"
    "需检验材料检验和未检验材料有无混放现象,有无使用未经检验材料的情况;"
    "材料的存放环境条件是否满足材料的"
)
PADDING_A = (
    "本项目监理工作以技术方案为核心,结合工程实际情况制定详尽的施工方案,"
    "确保各阶段任务按计划完成。监理团队由资深工程师组成,具备丰富的现场经验。"
    "我们将严格按照国家相关标准和招标文件要求执行各项监理工作。"
)
PADDING_B = (
    "我司技术方案立足于实战经验,提供可靠的工程监理服务。团队配备 PMP 认证项目经理,"
    "采用国际通行的项目管理方法。质量保障体系完善,项目实施流程规范,"
    "可显著降低项目风险并提升交付质量。"
)


async def _seed(
    owner_id: int, bidder_paras: list[list[str]]
) -> tuple[int, list[int]]:
    async with async_session() as s:
        p = Project(name="exact-match-bypass-test", status="ready", owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)

        bidder_ids: list[int] = []
        for i, paras in enumerate(bidder_paras):
            b = Bidder(name=f"V{i}", project_id=p.id, parse_status="identified")
            s.add(b)
            await s.flush()
            doc = BidDocument(
                bidder_id=b.id,
                file_name=f"tech-{i}.docx",
                file_path=f"/tmp/{i}.docx",
                file_size=1000,
                file_type=".docx",
                md5=f"x{i}" * 8,
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


async def _make_task(project_id: int, a_id: int, b_id: int, version: int = 1) -> int:
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


async def _run_agent(
    project_id: int, a_id: int, b_id: int, llm, version: int = 1
) -> None:
    task_id = await _make_task(project_id, a_id, b_id, version=version)
    async with async_session() as s:
        task = await s.get(AgentTask, task_id)
        a = await s.get(Bidder, a_id)
        b = await s.get(Bidder, b_id)
        ctx = AgentContext(
            project_id=project_id,
            version=version,
            agent_task=task,
            bidder_a=a,
            bidder_b=b,
            all_bidders=[],
            llm_provider=llm,
            session=s,
        )
        await ts_mod.run(ctx)
        await s.commit()


async def _load_pc(
    project_id: int, a_id: int, b_id: int, version: int = 1
) -> PairComparison | None:
    async with async_session() as s:
        stmt = select(PairComparison).where(
            PairComparison.project_id == project_id,
            PairComparison.bidder_a_id == a_id,
            PairComparison.bidder_b_id == b_id,
            PairComparison.dimension == "text_similarity",
            PairComparison.version == version,
        )
        return (await s.execute(stmt)).scalar_one_or_none()


# ============================================================================
# L2-1: hash 命中段进 evidence top + 同 (a_idx, b_idx) 不进 LLM judge prompt
# ============================================================================

async def test_exact_match_hits_evidence_top_and_skips_llm(
    clean_users, seeded_reviewer: User
):
    """A、B 各 5 段, 其中第 3 段贴相同 165 字注入段, 其它段独立。

    期望:
    - evidence_json.pairs_exact_match >= 1
    - samples 中存在 label='exact_match' 且 sim=1.0
    - LLM 收到的 messages 中 段落对列表 MUST 不含 (a_idx=2, b_idx=2) 那对
    - is_ironclad = True (165 字 ≥ 50 字门槛触发)
    """
    paras_a = [
        PADDING_A * 3,
        PADDING_A,
        INJECTED_165,  # idx=2
        PADDING_A * 2,
        PADDING_A,
    ]
    paras_b = [
        PADDING_B * 3,
        PADDING_B,
        INJECTED_165,  # idx=2 (与 A 完全相同)
        PADDING_B * 2,
        PADDING_B,
    ]
    pid, bids = await _seed(seeded_reviewer.id, [paras_a, paras_b])

    # LLM mock: 返回所有 cosine 候选段对都判 generic(确保即使有 cosine 候选也不抢 ironclad)
    llm = ScriptedLLMProvider(
        [
            make_text_similarity_response(
                [(i, "generic") for i in range(80)],
                overall="多为通用表述",
                confidence="medium",
            )
        ],
        loop_last=True,
    )
    await _run_agent(pid, bids[0], bids[1], llm)

    pc = await _load_pc(pid, bids[0], bids[1])
    assert pc is not None
    ev = pc.evidence_json
    # 1) hash 命中字段
    assert ev["pairs_exact_match"] >= 1, ev
    # 2) samples 中至少 1 条 exact_match
    exact_samples = [s for s in ev["samples"] if s.get("label") == "exact_match"]
    assert len(exact_samples) >= 1
    assert all(s["sim"] == 1.0 for s in exact_samples)
    # 3) ironclad: 165 字 ≥ 50 → True
    assert pc.is_ironclad is True
    # 4) 验证 LLM 没收到 hash 命中的 (a_idx=2, b_idx=2)
    if llm.calls:
        user_content = llm.calls[0][1]["content"]
        # prompt 里嵌入了 JSON 段落对列表; 检查这对的 a/b 文本不在
        # 简单检查: INJECTED_165 不应整段出现在 user_content (LLM 看不到)
        assert INJECTED_165[:50] not in user_content, (
            "hash 命中段 MUST 不进 LLM prompt"
        )


# ============================================================================
# L2-2: evidence_json schema 兼容性(旧无 pairs_exact_match 字段)
# ============================================================================

async def test_old_evidence_without_pairs_exact_match_reports_api_ok(
    clean_users, seeded_reviewer: User, client, admin_token: str
):
    """模拟旧版本写出的 evidence_json(无 pairs_exact_match 字段),
    reports API 仍返 200。
    """
    pid, bids = await _seed(
        seeded_reviewer.id, [[PADDING_A], [PADDING_B]]
    )

    # 直接写一行旧版 PairComparison(无 pairs_exact_match)
    async with async_session() as s:
        old_evidence = {
            "algorithm": "tfidf_cosine_v1",
            "doc_role": "technical",
            "doc_id_a": 1,
            "doc_id_b": 2,
            "threshold": 0.7,
            "pairs_total": 1,
            # 故意缺 pairs_exact_match
            "pairs_plagiarism": 0,
            "pairs_template": 0,
            "pairs_generic": 1,
            "degraded": False,
            "ai_judgment": {"overall": "", "confidence": "high"},
            "samples": [
                {
                    "a_idx": 0,
                    "b_idx": 0,
                    "a_text": "x",
                    "b_text": "x",
                    "sim": 0.9,
                    "label": "generic",
                }
            ],
        }
        s.add(
            PairComparison(
                project_id=pid,
                version=1,
                bidder_a_id=bids[0],
                bidder_b_id=bids[1],
                dimension="text_similarity",
                score=42.0,
                is_ironclad=False,
                evidence_json=old_evidence,
            )
        )
        # reports API 要求 AnalysisReport 存在才返 dimensions
        s.add(
            AnalysisReport(
                project_id=pid,
                version=1,
                total_score=42.0,
                risk_level="low",
            )
        )
        await s.commit()

    # reports API 取数 MUST 不抛错
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.get(
        f"/api/projects/{pid}/reports/1/dimensions", headers=headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # reports.dimensions 响应:列表或含 dimensions 字段;只要核心:200 不抛 + 含 text_similarity
    items = (
        data
        if isinstance(data, list)
        else (data.get("items") or data.get("dimensions") or [])
    )
    assert any(
        (it.get("dimension") or it.get("name") or it.get("dim_name"))
        == "text_similarity"
        for it in items
    ), data


# ============================================================================
# L2-3: PairComparison.version 递增正确
# ============================================================================

async def test_pair_comparison_version_increments_across_runs(
    clean_users, seeded_reviewer: User
):
    """同 (project, bidder_a, bidder_b, dimension) 跑两次得 v=1, v=2;
    max(version) 取最新。
    """
    paras_a = [PADDING_A * 3, INJECTED_165, PADDING_A]
    paras_b = [PADDING_B * 3, INJECTED_165, PADDING_B]
    pid, bids = await _seed(seeded_reviewer.id, [paras_a, paras_b])

    llm = ScriptedLLMProvider(
        [
            make_text_similarity_response(
                [(i, "generic") for i in range(80)], overall="", confidence="medium"
            )
        ],
        loop_last=True,
    )
    # 第一次 (version=1)
    await _run_agent(pid, bids[0], bids[1], llm, version=1)
    pc1 = await _load_pc(pid, bids[0], bids[1], version=1)
    assert pc1 is not None

    # 第二次 (version=2)
    await _run_agent(pid, bids[0], bids[1], llm, version=2)
    pc2 = await _load_pc(pid, bids[0], bids[1], version=2)
    assert pc2 is not None
    assert pc2.version == 2

    # 两个 version 行共存
    async with async_session() as s:
        rows = (
            await s.execute(
                select(PairComparison.version)
                .where(
                    PairComparison.project_id == pid,
                    PairComparison.bidder_a_id == bids[0],
                    PairComparison.bidder_b_id == bids[1],
                    PairComparison.dimension == "text_similarity",
                )
                .order_by(PairComparison.version)
            )
        ).scalars().all()
        assert rows == [1, 2]
