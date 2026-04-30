"""L2 - text_similarity Agent baseline 段级注入端到端 (detect-tender-baseline §3.6)

覆盖 spec ADD Req "4 高优 detector 接入 baseline 注入点" 全链路:
- tender 上传 → 检测 → evidence_json.baseline_source='tender' 段被剔除 ironclad
- 共识路径(无 tender + ≥3 bidders 同段)→ baseline_source='consensus' 段被剔除
- L3 ≤2 投标方 → warnings 写入 evidence_json,**ironclad 仍按原规则触发**(基线缺失 ≠ 信号无效)
- 老路径(无 tender,≥3 bidders 各异段) → baseline_source='none' + 原 ironclad 触发不变

策略:
- 真实 DB(TEST_DATABASE_URL)+ async_session
- 段级 segment_hash 入 DocumentText.segment_hash + TenderDocument.segment_hashes(sha256 + _normalize 口径)
- monkeypatch LLM provider(degraded=False 但无 plagiarism 判定避免 cosine 走出额外铁证路径)
- 构造 ≥50 字 exact_match 段(归一化后)模拟现网真实模板"
"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_text import DocumentText
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.models.tender_document import TenderDocument
from app.models.user import User
from app.services.detect.agents import text_similarity as ts_mod
from app.services.detect.agents.text_sim_impl.tfidf import _normalize
from app.services.detect.context import AgentContext
from tests.fixtures.llm_mock import (
    ScriptedLLMProvider,
    make_text_similarity_response,
)

pytestmark = pytest.mark.asyncio


# ============================================================ Fixtures (>=50 字归一化)


# ≥50 字 baseline 段(招标方下发的"模板格式"段落)
TEMPLATE_SEG = (
    "投标人就上述项目向招标人提交投标文件并承诺遵守本招标文件中"
    "的所有条款条件并自开标日起六十日内不可撤销有效。"
)
# ≥50 字非 baseline 段(独立撰写的真实抄袭段)
PLAGIARISM_SEG = (
    "项目核心采用先进 AI 技术结合机器学习算法识别投标文件中的串通"
    "围标行为为发标方提供合规审查辅助决策依据。"
)
# 短 padding 段(撑过 preflight MIN_DOC_CHARS,但 < 50 字归一化不触发 ironclad)
SHORT_PADDING = "本段为常规说明短文本不参与铁证判定"


def _seg_hash_sha256(text: str) -> str:
    """与 parser content._compute_segment_hash 口径统一(sha256 + _normalize)。"""
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


# ============================================================ Seeders


async def _seed_two_bidder_with_paragraphs(
    *,
    owner_id: int,
    bidder_a_paragraphs: list[str],
    bidder_b_paragraphs: list[str],
    tender_segment_hashes: list[str] | None = None,
    tag: str = "ts_baseline",
) -> tuple[int, int, int]:
    """构造 project + 2 bidder + 各自 BidDocument/DocumentText(seg_hash 入库)
    + 可选 TenderDocument(parse_status='extracted',segment_hashes 列表)。

    Returns (project_id, bidder_a_id, bidder_b_id)
    """
    async with async_session() as s:
        project = Project(name=f"P_{tag}", owner_id=owner_id, status="ready")
        s.add(project)
        await s.flush()

        async def _seed_bidder(letter: str, paragraphs: list[str]) -> int:
            b = Bidder(
                name=f"{letter}_{tag}",
                project_id=project.id,
                parse_status="extracted",
            )
            s.add(b)
            await s.flush()
            doc = BidDocument(
                bidder_id=b.id,
                file_name=f"tech_{letter}.docx",
                file_path=f"/tmp/{letter}.docx",
                file_size=2048,
                file_type=".docx",
                md5=f"md5_{tag}_{letter}",
                file_role="technical",
                parse_status="content_parsed",
                source_archive=f"{letter}.zip",
            )
            s.add(doc)
            await s.flush()
            for idx, text in enumerate(paragraphs):
                s.add(
                    DocumentText(
                        bid_document_id=doc.id,
                        paragraph_index=idx,
                        text=text,
                        location="body",
                        segment_hash=(
                            _seg_hash_sha256(text)
                            if len(_normalize(text)) >= 5
                            else None
                        ),
                    )
                )
            return b.id

        a_id = await _seed_bidder("A", bidder_a_paragraphs)
        b_id = await _seed_bidder("B", bidder_b_paragraphs)

        if tender_segment_hashes is not None:
            tender = TenderDocument(
                project_id=project.id,
                file_name=f"tender_{tag}.zip",
                file_path=f"/tmp/tender_{tag}.zip",
                file_size=4096,
                md5=f"t_{tag}",
                parse_status="extracted",
                segment_hashes=tender_segment_hashes,
                boq_baseline_hashes=[],
            )
            s.add(tender)
            await s.flush()

        await s.commit()
        return project.id, a_id, b_id


async def _seed_third_bidder(
    project_id: int,
    *,
    paragraphs: list[str],
    tag: str = "ts_baseline",
) -> int:
    """补第三家投标方(用于共识场景测试)。"""
    async with async_session() as s:
        b = Bidder(
            name=f"C_{tag}",
            project_id=project_id,
            parse_status="extracted",
        )
        s.add(b)
        await s.flush()
        doc = BidDocument(
            bidder_id=b.id,
            file_name="tech_C.docx",
            file_path="/tmp/C.docx",
            file_size=2048,
            file_type=".docx",
            md5=f"md5_{tag}_C",
            file_role="technical",
            parse_status="content_parsed",
            source_archive="C.zip",
        )
        s.add(doc)
        await s.flush()
        for idx, text in enumerate(paragraphs):
            s.add(
                DocumentText(
                    bid_document_id=doc.id,
                    paragraph_index=idx,
                    text=text,
                    location="body",
                    segment_hash=(
                        _seg_hash_sha256(text)
                        if len(_normalize(text)) >= 5
                        else None
                    ),
                )
            )
        await s.commit()
        return b.id


async def _run_text_similarity(
    project_id: int, a_id: int, b_id: int, llm_provider
) -> None:
    """构造 ctx 调 text_similarity.run() 写 PC 行。"""
    async with async_session() as s:
        a = await s.get(Bidder, a_id)
        b = await s.get(Bidder, b_id)
        task = AgentTask(
            project_id=project_id,
            version=1,
            agent_name="text_similarity",
            agent_type="pair",
            pair_bidder_a_id=a_id,
            pair_bidder_b_id=b_id,
            status="pending",
        )
        s.add(task)
        await s.flush()
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


async def _load_pc(project_id: int, a_id: int, b_id: int) -> PairComparison:
    async with async_session() as s:
        stmt = select(PairComparison).where(
            PairComparison.project_id == project_id,
            PairComparison.bidder_a_id == a_id,
            PairComparison.bidder_b_id == b_id,
            PairComparison.dimension == "text_similarity",
        )
        return (await s.execute(stmt)).scalar_one()


def _scripted_no_plagiarism_llm() -> ScriptedLLMProvider:
    """LLM 返 generic(无 plagiarism)→ cosine 路径不走 ironclad,排除变量。"""
    return ScriptedLLMProvider(
        [
            make_text_similarity_response(
                [(i, "generic") for i in range(30)],
                overall="无显著抄袭",
                confidence="high",
            )
        ],
        loop_last=True,
    )


# ============================================================ Tests


async def test_l1_tender_match_skips_ironclad(
    clean_users, seeded_reviewer: User
):
    """L1 tender 命中场景:
    A/B 两家文档完全相同(都是 TEMPLATE_SEG),tender 含同 hash →
    PC.is_ironclad=False(段被跳过),evidence_json.baseline_source='tender',
    samples[*].baseline_matched=True(命中段)。"""
    paras = [TEMPLATE_SEG] * 5  # 重复段 + 撑过 MIN_DOC_CHARS
    pid, a_id, b_id = await _seed_two_bidder_with_paragraphs(
        owner_id=seeded_reviewer.id,
        bidder_a_paragraphs=paras,
        bidder_b_paragraphs=paras,
        tender_segment_hashes=[_seg_hash_sha256(TEMPLATE_SEG)],
        tag="l1_tender_hit",
    )

    await _run_text_similarity(pid, a_id, b_id, _scripted_no_plagiarism_llm())

    pc = await _load_pc(pid, a_id, b_id)
    assert pc.evidence_json["baseline_source"] == "tender", pc.evidence_json
    assert pc.is_ironclad is False, "tender 命中段 MUST 跳过 ironclad"
    # 至少一个 sample 标 baseline_matched=True
    matched_samples = [
        s for s in pc.evidence_json["samples"] if s.get("baseline_matched")
    ]
    assert len(matched_samples) >= 1
    assert all(
        s["baseline_source"] == "tender" for s in matched_samples
    )


async def test_no_tender_no_consensus_ironclad_triggers(
    clean_users, seeded_reviewer: User
):
    """无 tender + 仅 2 bidders + 段相同 → L3 警示但 ironclad 仍 MUST 触发。

    spec scenario "L3 投标方 ≤2 仍可独自顶铁证":
    - is_ironclad=True(原触发条件成立)
    - evidence_json.baseline_source='none'
    - evidence_json.warnings 含 'baseline_unavailable_low_bidder_count'
    """
    paras = [TEMPLATE_SEG] * 5
    pid, a_id, b_id = await _seed_two_bidder_with_paragraphs(
        owner_id=seeded_reviewer.id,
        bidder_a_paragraphs=paras,
        bidder_b_paragraphs=paras,
        tender_segment_hashes=None,  # 无 tender
        tag="l3_two_bidders",
    )

    await _run_text_similarity(pid, a_id, b_id, _scripted_no_plagiarism_llm())

    pc = await _load_pc(pid, a_id, b_id)
    assert pc.evidence_json["baseline_source"] == "none"
    assert "baseline_unavailable_low_bidder_count" in pc.evidence_json["warnings"]
    # L3 立场:基线缺失 ≠ 信号无效,≥50 字 exact_match 仍触发铁证
    assert pc.is_ironclad is True
    # samples 段级标记:无 baseline 全为 false/none
    for s in pc.evidence_json["samples"]:
        assert s["baseline_matched"] is False
        assert s["baseline_source"] == "none"


async def test_l2_consensus_match_skips_ironclad(
    clean_users, seeded_reviewer: User
):
    """无 tender + 3 bidders 同段(共识 ≥3)→ baseline_source='consensus' +
    is_ironclad=False(段被跳过)。"""
    paras = [TEMPLATE_SEG] * 5
    pid, a_id, b_id = await _seed_two_bidder_with_paragraphs(
        owner_id=seeded_reviewer.id,
        bidder_a_paragraphs=paras,
        bidder_b_paragraphs=paras,
        tender_segment_hashes=None,
        tag="l2_consensus_hit",
    )
    # 补第三家也同段
    await _seed_third_bidder(pid, paragraphs=paras, tag="l2_consensus_hit")

    await _run_text_similarity(pid, a_id, b_id, _scripted_no_plagiarism_llm())

    pc = await _load_pc(pid, a_id, b_id)
    assert pc.evidence_json["baseline_source"] == "consensus"
    assert pc.is_ironclad is False, "consensus 命中段 MUST 跳过 ironclad"


async def test_partial_baseline_match_still_triggers_ironclad(
    clean_users, seeded_reviewer: User
):
    """spec scenario "PC 内部分段命中 baseline 不豁免整 PC":
    A/B 共有 2 段 ≥50 字 — 1 段是 tender 模板,1 段是真抄袭 →
    is_ironclad=True(按未命中段判定),baseline_source='tender'(顶级取最强)。"""
    # 2 段都 ≥50 字归一化;TEMPLATE_SEG 在 tender 集合,PLAGIARISM_SEG 不在
    paras = [TEMPLATE_SEG, PLAGIARISM_SEG, SHORT_PADDING * 5]
    pid, a_id, b_id = await _seed_two_bidder_with_paragraphs(
        owner_id=seeded_reviewer.id,
        bidder_a_paragraphs=paras,
        bidder_b_paragraphs=paras,
        tender_segment_hashes=[_seg_hash_sha256(TEMPLATE_SEG)],
        tag="partial_hit",
    )

    await _run_text_similarity(pid, a_id, b_id, _scripted_no_plagiarism_llm())

    pc = await _load_pc(pid, a_id, b_id)
    # 顶级 baseline_source='tender'(命中段最强 source)
    assert pc.evidence_json["baseline_source"] == "tender"
    # 非 tender 命中段 PLAGIARISM_SEG ≥50 字仍升铁证
    assert pc.is_ironclad is True
    # samples 段级混合:TEMPLATE_SEG 命中、PLAGIARISM_SEG 未命中
    matched = [
        s for s in pc.evidence_json["samples"] if s.get("baseline_matched")
    ]
    unmatched = [
        s
        for s in pc.evidence_json["samples"]
        if not s.get("baseline_matched")
    ]
    assert len(matched) >= 1
    assert len(unmatched) >= 1


async def test_evidence_legacy_compat_when_baseline_arg_omitted(
    clean_users, seeded_reviewer: User
):
    """老路径(无 tender + 3 bidders + 段全各异)→ baseline_source='none' + warnings=[];
    evidence schema 保留所有老字段(algorithm / pairs_total / samples 等)。

    关键:每家所有段都唯一(包括 padding),避免触发 consensus(共识 ≥3 家同段会
    把"任意 3 家共有段"识别为模板基线)。"""
    # A 段、B 段、C 段全部独立 + 各自独立 padding(每家 padding 内容也不同)
    paras_a = [
        PLAGIARISM_SEG,
        # ≥50 字归一化的 A 专用 padding
        "本投标方郑重承诺所有声明均属实并接受贵方的资格审查与合同后续监督",
    ]
    paras_b = [
        # B 段独立(不与 A 重合,不触发 cosine 阈值)
        "饮食搭配应当均衡多吃蔬菜水果富含维生素和膳食纤维有助于身体健康早睡早起调节身心保持愉悦运动锻炼持之以恒方能收效",
        # B 专用 padding,与 A/C 不同
        "B 公司多年专注于建筑行业并通过省级双优施工企业评审凭借扎实管理体系赢得客户口碑",
    ]
    pid, a_id, b_id = await _seed_two_bidder_with_paragraphs(
        owner_id=seeded_reviewer.id,
        bidder_a_paragraphs=paras_a,
        bidder_b_paragraphs=paras_b,
        tender_segment_hashes=None,
        tag="legacy_compat",
    )
    # 补第 3 家段也独立(避免 L3 警示),padding 也独立
    await _seed_third_bidder(
        pid,
        paragraphs=[
            "项目计划由项目部组织全员开展月度进度回顾对照里程碑节点检视技术团队工程团队商务团队的关键交付物完成情况",
            "C 单位长期深耕华东市场凭借专业团队及完善供应链获得多项行业奖项",
        ],
        tag="legacy_compat",
    )

    await _run_text_similarity(pid, a_id, b_id, _scripted_no_plagiarism_llm())

    pc = await _load_pc(pid, a_id, b_id)
    # baseline_source='none' + warnings=[](≥3 bidders 不出 L3 警示)
    assert pc.evidence_json["baseline_source"] == "none", pc.evidence_json
    assert pc.evidence_json["warnings"] == []
    # 老字段保留
    assert pc.evidence_json["algorithm"] == "tfidf_cosine_v1"
    assert "pairs_total" in pc.evidence_json
    assert "samples" in pc.evidence_json
