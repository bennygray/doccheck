"""L2 - section_similarity Agent 真实章节级链路 (C8)

覆盖 execution-plan §3 C8 的 4 scenario:
1. 章节雷同命中 → score ≥ 60 + is_ironclad + chapter_pairs 含铁证章节
2. 章节错位对齐 → aligned_by='title',不同 idx 配对
3. 识别失败降级 → evidence.degraded_to_doc_level=true
4. 极少章节降级 → 一侧 < MIN_CHAPTERS → 降级但 status=succeeded

策略同 C7:手工构造 ctx 直调 Agent.run(),绕开 engine/SSE 验算法层。
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
from app.services.detect.agents import section_similarity as ss_mod
from app.services.detect.context import AgentContext
from tests.fixtures.llm_mock import (
    ScriptedLLMProvider,
    make_section_similarity_response,
)

pytestmark = pytest.mark.asyncio


# ---------- seed helpers ----------

async def _seed_project_and_bidders(
    owner_id: int,
    bidder_paragraph_lists: list[list[str]],
) -> tuple[int, list[int]]:
    async with async_session() as s:
        p = Project(name="c8-test", status="ready", owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)

        bidder_ids: list[int] = []
        for i, paras in enumerate(bidder_paragraph_lists):
            b = Bidder(name=f"B{i}", project_id=p.id, parse_status="identified")
            s.add(b)
            await s.flush()
            doc = BidDocument(
                bidder_id=b.id, file_name=f"tech-{i}.docx", file_path=f"/tmp/{i}.docx",
                file_size=1000, file_type=".docx", md5=f"c8m{i}" * 8,
                file_role="technical", parse_status="content_parsed",
                source_archive=f"a{i}.zip",
            )
            s.add(doc)
            await s.flush()
            for idx, text in enumerate(paras):
                s.add(DocumentText(
                    bid_document_id=doc.id, paragraph_index=idx,
                    text=text, location="body",
                ))
            bidder_ids.append(b.id)
        await s.commit()
        return p.id, bidder_ids


async def _run_section_sim(
    project_id: int, a_id: int, b_id: int, llm_provider,
) -> None:
    async with async_session() as s:
        a = await s.get(Bidder, a_id)
        b = await s.get(Bidder, b_id)
        task = AgentTask(
            project_id=project_id, version=1, agent_name="section_similarity",
            agent_type="pair", pair_bidder_a_id=a.id, pair_bidder_b_id=b.id,
            status="pending",
        )
        s.add(task)
        await s.flush()
        ctx = AgentContext(
            project_id=project_id, version=1, agent_task=task,
            bidder_a=a, bidder_b=b, all_bidders=[],
            llm_provider=llm_provider, session=s,
        )
        await ss_mod.run(ctx)
        await s.commit()


async def _load_pc(project_id: int, a_id: int, b_id: int) -> PairComparison | None:
    async with async_session() as s:
        stmt = select(PairComparison).where(
            PairComparison.project_id == project_id,
            PairComparison.bidder_a_id == a_id,
            PairComparison.bidder_b_id == b_id,
            PairComparison.dimension == "section_similarity",
        )
        return (await s.execute(stmt)).scalar_one_or_none()


# ---------- 文档构造 ----------

def _mk_chapter(num: str, title: str, body: str, repeats: int = 2) -> list[str]:
    """返 [章节标题, 段落1, 段落2, ...]。body repeats 次保证 > MIN_CHAPTER_CHARS。"""
    return [f"{num} {title}", *([body] * repeats)]


_TECH_BODY_A = "本项目采用先进的人工智能技术方案,实现自动化分析。团队具备十年经验。" * 3
_TECH_BODY_B_COPY = _TECH_BODY_A
_TECH_BODY_INDEPENDENT = "饮食均衡对身体有益,多吃蔬菜。运动锻炼需持之以恒。" * 3


def _standard_3_chapter_doc(
    first_body: str, second_body: str, third_body: str,
) -> list[str]:
    """标准 3 章节文档(投标函 / 技术方案 / 商务标)。"""
    return (
        _mk_chapter("第一章", "投标函", first_body)
        + _mk_chapter("第二章", "技术方案", second_body)
        + _mk_chapter("第三章", "商务标", third_body)
    )


# ---------- Scenario 1: 章节雷同命中 ----------

async def test_section_similarity_chapter_plagiarism_hit(
    clean_users, seeded_reviewer: User
):
    paras_a = _standard_3_chapter_doc(_TECH_BODY_A, _TECH_BODY_A, _TECH_BODY_A)
    paras_b = _standard_3_chapter_doc(
        _TECH_BODY_B_COPY, _TECH_BODY_B_COPY, _TECH_BODY_B_COPY
    )
    pid, bids = await _seed_project_and_bidders(
        seeded_reviewer.id, [paras_a, paras_b]
    )

    llm = ScriptedLLMProvider(
        [make_section_similarity_response(
            [(i, "plagiarism") for i in range(30)],
            overall="章节级同源抄袭",
            confidence="high",
        )],
        loop_last=True,
    )
    await _run_section_sim(pid, bids[0], bids[1], llm)

    pc = await _load_pc(pid, bids[0], bids[1])
    assert pc is not None
    assert pc.evidence_json["algorithm"] == "tfidf_cosine_chapter_v1"
    assert pc.evidence_json["degraded_to_doc_level"] is False
    assert float(pc.score) >= 60.0
    assert pc.is_ironclad is True
    assert len(pc.evidence_json["chapter_pairs"]) >= 1
    # 至少一个章节对 is_chapter_ironclad
    assert any(cp["is_chapter_ironclad"] for cp in pc.evidence_json["chapter_pairs"])


# ---------- Scenario 2: 章节错位对齐 ----------

async def test_section_similarity_title_alignment_across_idx(
    clean_users, seeded_reviewer: User
):
    """A 5 章节,B 4 章节,"技术方案" 在不同 idx → title 对齐仍命中。"""
    # A: 0=投标函 1=商务 2=技术方案 3=资质 4=附录
    paras_a = (
        _mk_chapter("第一章", "投标函", _TECH_BODY_INDEPENDENT)
        + _mk_chapter("第二章", "商务标", _TECH_BODY_INDEPENDENT)
        + _mk_chapter("第三章", "技术方案", _TECH_BODY_A)  # 抄袭源
        + _mk_chapter("第四章", "资质证明", _TECH_BODY_INDEPENDENT)
        + _mk_chapter("第五章", "附录", _TECH_BODY_INDEPENDENT)
    )
    # B: 0=商务 1=投标函 2=资质 3=技术方案(在 idx=3 不是 2)
    paras_b = (
        _mk_chapter("第一章", "商务标", _TECH_BODY_INDEPENDENT)
        + _mk_chapter("第二章", "投标函", _TECH_BODY_INDEPENDENT)
        + _mk_chapter("第三章", "资质证明", _TECH_BODY_INDEPENDENT)
        + _mk_chapter("第四章", "技术方案", _TECH_BODY_B_COPY)  # 抄 A 的技术方案
    )
    pid, bids = await _seed_project_and_bidders(seeded_reviewer.id, [paras_a, paras_b])

    llm = ScriptedLLMProvider(
        [make_section_similarity_response(
            [(i, "plagiarism") for i in range(30)],
            overall="技术方案章节同源",
            confidence="high",
        )],
        loop_last=True,
    )
    await _run_section_sim(pid, bids[0], bids[1], llm)

    pc = await _load_pc(pid, bids[0], bids[1])
    assert pc is not None
    assert pc.evidence_json["degraded_to_doc_level"] is False
    # 应有至少一个 aligned_by='title' 的章节对(技术方案 vs 技术方案)
    title_pairs = [
        cp for cp in pc.evidence_json["chapter_pairs"]
        if cp["aligned_by"] == "title"
    ]
    assert len(title_pairs) >= 1
    # 技术方案 vs 技术方案 应该是 title 对齐
    tech_alignment = [
        cp for cp in title_pairs
        if "技术方案" in cp["a_title"] and "技术方案" in cp["b_title"]
    ]
    assert len(tech_alignment) == 1
    assert tech_alignment[0]["a_idx"] != tech_alignment[0]["b_idx"]  # 错位 idx


# ---------- Scenario 3: 识别失败降级 ----------

async def test_section_similarity_no_chapter_pattern_fallbacks(
    clean_users, seeded_reviewer: User
):
    """双方均无章节标题行 → chapters=[] → 降级整文档。"""
    # 段落无任何章节 PATTERN 匹配
    body1 = "本公司投标内容说明如下：" * 30
    body2 = "团队经验介绍：" * 30
    body3 = "技术方案阐述：" * 30
    plain_a = [body1, body2, body3]
    plain_b = [body1, body2, body3]
    pid, bids = await _seed_project_and_bidders(seeded_reviewer.id, [plain_a, plain_b])

    llm = ScriptedLLMProvider(
        [make_section_similarity_response(
            [(i, "plagiarism") for i in range(30)],
            overall="整文档降级命中",
            confidence="high",
        )],
        loop_last=True,
    )
    await _run_section_sim(pid, bids[0], bids[1], llm)

    pc = await _load_pc(pid, bids[0], bids[1])
    assert pc is not None
    assert pc.evidence_json["algorithm"] == "tfidf_cosine_fallback_to_doc"
    assert pc.evidence_json["degraded_to_doc_level"] is True
    assert pc.evidence_json["chapters_a_count"] == 0
    assert pc.evidence_json["chapters_b_count"] == 0
    assert pc.evidence_json["chapter_pairs"] == []
    assert pc.evidence_json["aligned_count"] == 0


# ---------- Scenario 4: 极少章节降级 ----------

async def test_section_similarity_too_few_chapters_fallbacks(
    clean_users, seeded_reviewer: User
):
    """A 1 章节(< MIN_CHAPTERS=3),B 3 章节 → 触发降级。"""
    paras_a = _mk_chapter("第一章", "投标函", _TECH_BODY_A, repeats=4)  # 单章节
    paras_b = _standard_3_chapter_doc(
        _TECH_BODY_B_COPY, _TECH_BODY_B_COPY, _TECH_BODY_B_COPY
    )
    pid, bids = await _seed_project_and_bidders(seeded_reviewer.id, [paras_a, paras_b])

    llm = ScriptedLLMProvider(
        [make_section_similarity_response(
            [(i, "plagiarism") for i in range(30)],
            overall="整文档降级",
            confidence="high",
        )],
        loop_last=True,
    )
    await _run_section_sim(pid, bids[0], bids[1], llm)

    pc = await _load_pc(pid, bids[0], bids[1])
    assert pc is not None
    assert pc.evidence_json["degraded_to_doc_level"] is True
    assert pc.evidence_json["chapters_a_count"] == 1
    assert pc.evidence_json["chapters_b_count"] == 3
    # status 仍是 succeeded(降级不算失败)— 我们直接调 run() 不走 engine status 更新
    # 验 PairComparison 行存在即证明 run() 正常完成
    assert float(pc.score) > 0  # 整文档降级后仍有分数
