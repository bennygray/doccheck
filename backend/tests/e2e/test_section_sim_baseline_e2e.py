"""L2 - section_similarity Agent baseline 端到端 (detect-tender-baseline §4.4)

覆盖 spec ADD Req "4 高优 detector 接入 baseline 注入点" 章节级 + 段级 baseline 命中:
- L1 tender 章节标题命中 → 整章节 is_chapter_ironclad=False
- L1 tender 段级命中 → samples[i].baseline_matched=true,段级 ironclad 跳过
- 老路径(无 tender + 3 bidders 段全各异)→ baseline_source='none' + warnings=[],evidence schema 兼容
- L3 ≤2 投标方 + 无 tender → warnings 写入 + 章节标题 baseline 仍按原触发逻辑(不抑制)

策略:真 DB(TEST_DATABASE_URL),seed Document(包含章节)+ TenderDocument(段 hash 集),
script LLM 返 generic 避免 cosine 路径噪音,直接调 section_similarity.run()。
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
from app.services.detect.agents import section_similarity as ss_mod
from app.services.detect.agents.text_sim_impl.tfidf import _normalize
from app.services.detect.context import AgentContext
from tests.fixtures.llm_mock import (
    ScriptedLLMProvider,
    make_section_similarity_response,
)

pytestmark = pytest.mark.asyncio


def _seg_hash(text: str) -> str:
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


# ============================================================ Fixtures(>=50 字归一化避免合并稀释)


# 章节标题 - tender 命中段(归一化后 MUST ≥50 字否则 segmenter 会合并 title+body)
# chapter_parser 用 raw paragraphs 切章不受影响,但 fallback 路径走 merged segs
TEMPLATE_TITLE_1 = (
    "第二章 投标人就上述项目向招标人提交投标文件并承诺"
    "遵守招标文件中的所有条款条件六十日内不可撤销有效永久"
)
TEMPLATE_TITLE_2 = (
    "第三章 工程总承包合同条款及投标文件格式要求附件清单"
    "包含技术规范及商务条款详细说明书附件目录索引完整版本"
)
TEMPLATE_TITLE_3 = (
    "第四章 投标人资质审查条件商业及技术条款公告期限"
    "及评标办法与流程详细规则附件五附件六附件七全部完整保留"
)
# 章节内 baseline 段(模板 boilerplate,≥50 字)
TEMPLATE_PARA = (
    "本投标人按招标文件要求提交完整密封报价并自愿承担因本"
    "投标文件造成的一切法律责任和后果不可撤回有效永久"
)
# 非 baseline 内容(≥50 字)
PLAGIARISM_BODY = (
    "项目核心采用先进 AI 技术结合机器学习算法识别投标文件中的"
    "串通围标行为为发标方提供合规审查辅助决策依据有用"
)


def _assert_norm_len_at_least(text: str, n: int) -> None:
    actual = len(_normalize(text))
    assert actual >= n, f"text norm_len {actual} < {n}: {_normalize(text)!r}"


# Fixture 自检:所有标题 + 段在 norm_len ≥ 50,避免 segmenter 合并
_assert_norm_len_at_least(TEMPLATE_TITLE_1, 50)
_assert_norm_len_at_least(TEMPLATE_TITLE_2, 50)
_assert_norm_len_at_least(TEMPLATE_TITLE_3, 50)
_assert_norm_len_at_least(TEMPLATE_PARA, 50)
_assert_norm_len_at_least(PLAGIARISM_BODY, 50)


def _mk_chapter(title: str, body: str, repeats: int = 3) -> list[str]:
    """返 [章节标题, body 重复 N 次]。"""
    return [title, *([body] * repeats)]


# ============================================================ Seeders


async def _seed(
    *,
    owner_id: int,
    tag: str,
    bidders_paragraphs: list[list[str]],
    tender_segment_hashes: list[str] | None = None,
) -> tuple[int, list[int]]:
    """构造 project + N bidder + (可选) tender。"""
    async with async_session() as s:
        p = Project(name=f"P_{tag}", owner_id=owner_id, status="ready")
        s.add(p)
        await s.flush()

        bidder_ids: list[int] = []
        for i, paras in enumerate(bidders_paragraphs):
            b = Bidder(
                name=f"B{i}_{tag}", project_id=p.id, parse_status="extracted"
            )
            s.add(b)
            await s.flush()
            doc = BidDocument(
                bidder_id=b.id,
                file_name=f"tech-{i}.docx",
                file_path=f"/tmp/{tag}_{i}.docx",
                file_size=2048,
                file_type=".docx",
                md5=f"md5_{tag}_{i}",
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
                        segment_hash=(
                            _seg_hash(text)
                            if len(_normalize(text)) >= 5
                            else None
                        ),
                    )
                )
            bidder_ids.append(b.id)

        if tender_segment_hashes is not None:
            s.add(
                TenderDocument(
                    project_id=p.id,
                    file_name="模板.zip",
                    file_path=f"/tmp/tender_{tag}.zip",
                    file_size=4096,
                    md5=f"t_{tag}",
                    parse_status="extracted",
                    segment_hashes=tender_segment_hashes,
                    boq_baseline_hashes=[],
                )
            )

        await s.commit()
        return p.id, bidder_ids


async def _run_section_sim(project_id: int, a_id: int, b_id: int, llm) -> None:
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
            llm_provider=llm, session=s,
        )
        await ss_mod.run(ctx)
        await s.commit()


async def _load_pc(pid: int, a: int, b: int) -> PairComparison:
    async with async_session() as s:
        stmt = select(PairComparison).where(
            PairComparison.project_id == pid,
            PairComparison.bidder_a_id == a,
            PairComparison.bidder_b_id == b,
            PairComparison.dimension == "section_similarity",
        )
        return (await s.execute(stmt)).scalar_one()


def _scripted_no_plag_llm() -> ScriptedLLMProvider:
    return ScriptedLLMProvider(
        [
            make_section_similarity_response(
                [(i, "generic") for i in range(30)],
                overall="无显著抄袭",
                confidence="high",
            )
        ],
        loop_last=True,
    )


# ============================================================ Tests


async def test_l1_tender_chapter_title_match_skips_chapter_ironclad(
    clean_users, seeded_reviewer: User
):
    """L1 tender 章节标题命中 → 整章节 is_chapter_ironclad=False
    (即使段对全 plagiarism 也不顶铁证)。"""
    # 3 章节避免 fallback path(min_chapters=3)
    paras_a = (
        _mk_chapter(TEMPLATE_TITLE_1, TEMPLATE_PARA, repeats=3)
        + _mk_chapter(TEMPLATE_TITLE_2, TEMPLATE_PARA, repeats=3)
        + _mk_chapter(TEMPLATE_TITLE_3, TEMPLATE_PARA, repeats=3)
    )
    paras_b = list(paras_a)  # 完全相同
    pid, bids = await _seed(
        owner_id=seeded_reviewer.id,
        tag="ss_tender_title",
        bidders_paragraphs=[paras_a, paras_b],
        tender_segment_hashes=[
            _seg_hash(TEMPLATE_TITLE_1),
            _seg_hash(TEMPLATE_TITLE_2),
            _seg_hash(TEMPLATE_TITLE_3),
            _seg_hash(TEMPLATE_PARA),
        ],
    )
    # LLM 全判 plagiarism 测"章节标题命中应覆盖 LLM 判定"
    llm = ScriptedLLMProvider(
        [
            make_section_similarity_response(
                [(i, "plagiarism") for i in range(30)],
                overall="抄袭",
                confidence="high",
            )
        ],
        loop_last=True,
    )

    await _run_section_sim(pid, bids[0], bids[1], llm)
    pc = await _load_pc(pid, bids[0], bids[1])
    ev = pc.evidence_json
    assert ev.get("degraded_to_doc_level") is False, ev.get("degrade_reason")
    assert ev["baseline_source"] == "tender", ev.get("baseline_source")
    # 至少一个 chapter_pair 标记 chapter_baseline_matched
    matched_chapters = [
        cp for cp in ev["chapter_pairs"]
        if cp.get("chapter_baseline_matched")
    ]
    assert len(matched_chapters) >= 1
    # 命中章节 is_chapter_ironclad MUST = False(章节是模板,LLM 判 plag 也不顶)
    for cp in matched_chapters:
        assert cp["is_chapter_ironclad"] is False
        assert cp["chapter_baseline_source"] == "tender"
    # PC 整体也不顶铁证(若所有命中章节都是 baseline → is_ironclad=False)
    if all(cp.get("chapter_baseline_matched") for cp in ev["chapter_pairs"]):
        assert pc.is_ironclad is False


async def test_l1_tender_segment_match_marks_samples_baseline_matched(
    clean_users, seeded_reviewer: User
):
    """章节标题不在 baseline,但章节内段级 hash 命中 → samples[i].baseline_matched=true。"""
    # 3 章节避免 fallback;custom titles 不在 baseline,但 PARA 段在
    custom_title_1 = (
        "第一章 项目实施技术架构方案专题阐述详细的研发流程和管理"
        "制度规范化标准化的全程管理制度规范说明书完整版本独家原创"
    )
    custom_title_2 = (
        "第二章 团队人员配置专题与岗位职责详细阐述每个岗位的职能"
        "和工作要求标准化的全程管理制度规范说明书完整版本独家原创"
    )
    custom_title_3 = (
        "第三章 项目质量管理体系建设专题阐述质量控制流程和检验"
        "标准全过程把控制度规范说明书完整版本独家原创不可复制保留"
    )
    _assert_norm_len_at_least(custom_title_1, 50)
    _assert_norm_len_at_least(custom_title_2, 50)
    _assert_norm_len_at_least(custom_title_3, 50)
    paras_a = (
        _mk_chapter(custom_title_1, TEMPLATE_PARA, repeats=3)
        + _mk_chapter(custom_title_2, TEMPLATE_PARA, repeats=3)
        + _mk_chapter(custom_title_3, TEMPLATE_PARA, repeats=3)
    )
    paras_b = list(paras_a)
    pid, bids = await _seed(
        owner_id=seeded_reviewer.id,
        tag="ss_seg_match",
        bidders_paragraphs=[paras_a, paras_b],
        tender_segment_hashes=[_seg_hash(TEMPLATE_PARA)],  # 仅段级 baseline,不含标题
    )
    await _run_section_sim(pid, bids[0], bids[1], _scripted_no_plag_llm())

    pc = await _load_pc(pid, bids[0], bids[1])
    ev = pc.evidence_json
    # 章节级未命中(custom_title 不在 baseline)
    for cp in ev["chapter_pairs"]:
        assert cp["chapter_baseline_matched"] is False
    # 但段级命中 → PC 顶级 baseline_source='tender'(因为 sample 段命中)
    assert ev["baseline_source"] == "tender"
    # samples 段级标记
    matched_samples = []
    for cp in ev["chapter_pairs"]:
        # samples 在跨章节合并的顶级 evidence.samples 里取(_build_chapter_evidence)
        pass
    # 顶级 samples 至少一个标 baseline_matched
    matched_top = [s for s in ev["samples"] if s.get("baseline_matched")]
    assert len(matched_top) >= 1
    assert all(s["baseline_source"] == "tender" for s in matched_top)


async def test_no_tender_legacy_behavior(
    clean_users, seeded_reviewer: User
):
    """老路径(无 tender + 3 bidders + 段全各异)→ baseline_source='none' + warnings=[]
    + evidence schema 含 chapter_baseline_source 段级字段(默认 'none')(向后兼容)。"""
    # 3 章节满足 min_chapters,各家段独立避免 consensus
    # 每家章节标题各异(防止 ≥3 bidders 同标题触发 consensus);各 norm_len ≥ 50
    title_a_1 = "第一章 A 公司投标函章节目录索引及前言部分基本信息和声明完整版本独家原创不可复制保留制度规范说明书"
    title_a_2 = "第二章 A 公司商务标章节目录索引及前言部分商务条款合同条件独家原创版本完整版本独家原创不可复制保留"
    title_a_3 = "第三章 A 公司技术标章节目录索引及前言部分技术方案实施计划独家原创版本完整版本独家原创不可复制保留"
    title_b_1 = "第一章 B 公司投标函章节目录索引及前言部分基本信息和声明完整版本独家原创不可复制保留制度规范说明书"
    title_b_2 = "第二章 B 公司商务标章节目录索引及前言部分商务条款合同条件独家原创版本完整版本独家原创不可复制保留"
    title_b_3 = "第三章 B 公司技术标章节目录索引及前言部分技术方案实施计划独家原创版本完整版本独家原创不可复制保留"
    title_c_1 = "第一章 C 公司投标函章节目录索引及前言部分基本信息和声明完整版本独家原创不可复制保留制度规范说明书"
    title_c_2 = "第二章 C 公司商务标章节目录索引及前言部分商务条款合同条件独家原创版本完整版本独家原创不可复制保留"
    title_c_3 = "第三章 C 公司技术标章节目录索引及前言部分技术方案实施计划独家原创版本完整版本独家原创不可复制保留"
    for t in [title_a_1, title_a_2, title_a_3, title_b_1, title_b_2, title_b_3, title_c_1, title_c_2, title_c_3]:
        _assert_norm_len_at_least(t, 50)
    body_a_1 = "A 公司本投标函具体内容描述详尽充分有效不可撤销永久保留独家原创内容详细" * 2
    body_a_2 = "A 公司本商务标具体内容详尽充分独家原创不可复制独立编写完整版本永久"
    body_a_3 = "A 公司本技术标方案详尽充分独家原创不可复制独立编写完整版本永久保留"
    body_b_1 = "B 公司本投标函内容说明详细独立独家撰写完整不可篡改永久独家版本保留"
    body_b_2 = "B 公司本商务标内容说明详细独立独家撰写完整不可篡改永久独家保留"
    body_b_3 = "B 公司本技术标内容说明详细独立独家撰写完整不可篡改永久独家保留方案"
    body_c_1 = "C 公司本投标函编写依据合规标准独家原创内容完整版本永久保留独立编写"
    body_c_2 = "C 公司本商务标编写依据合规标准独家原创内容完整版本永久保留独立编"
    body_c_3 = "C 公司本技术标编写依据合规标准独家原创内容完整版本永久保留独立"
    paras_a = (
        _mk_chapter(title_a_1, body_a_1, 3)
        + _mk_chapter(title_a_2, body_a_2, 3)
        + _mk_chapter(title_a_3, body_a_3, 3)
    )
    paras_b = (
        _mk_chapter(title_b_1, body_b_1, 3)
        + _mk_chapter(title_b_2, body_b_2, 3)
        + _mk_chapter(title_b_3, body_b_3, 3)
    )
    paras_c = (
        _mk_chapter(title_c_1, body_c_1, 3)
        + _mk_chapter(title_c_2, body_c_2, 3)
        + _mk_chapter(title_c_3, body_c_3, 3)
    )
    pid, bids = await _seed(
        owner_id=seeded_reviewer.id,
        tag="ss_legacy",
        bidders_paragraphs=[paras_a, paras_b, paras_c],
        tender_segment_hashes=None,
    )
    await _run_section_sim(pid, bids[0], bids[1], _scripted_no_plag_llm())

    pc = await _load_pc(pid, bids[0], bids[1])
    ev = pc.evidence_json
    assert ev["baseline_source"] == "none"
    assert ev["warnings"] == []
    # algorithm 视章节切分成功与否走 main path 或 fallback path,均可
    assert ev["algorithm"] in {
        "tfidf_cosine_chapter_v1",
        "tfidf_cosine_fallback_to_doc",
    }
    # 主路径 chapter_pairs 默认值;fallback 路径 chapter_pairs=[](无章节级 baseline 标记)
    for cp in ev.get("chapter_pairs", []):
        assert cp.get("chapter_baseline_source") == "none"
        assert cp.get("chapter_baseline_matched") is False
    # samples 段级默认 false / none(向后兼容)
    for s in ev.get("samples", []):
        assert s.get("baseline_matched") is False
        assert s.get("baseline_source") == "none"


async def test_l3_two_bidders_ironclad_preserved(
    clean_users, seeded_reviewer: User
):
    """L3 ≤2 投标方 + 无 tender → warnings 写入 + 章节级 ironclad 仍按原规则触发
    (基线缺失 ≠ 信号无效)。"""
    # 3 章节满足 min_chapters=3
    title_1 = (
        "第一章 投标函章节文件目录索引及前言部分包含投标人基本信息"
        "和投标声明完整版本独家原创不可复制保留制度规范说明书内容版本"
    )
    title_2 = (
        "第二章 实施方案章节文件目录索引及前言部分包含投标人技术方案"
        "和实施计划完整版本独家原创不可复制保留制度规范说明书内容版本"
    )
    title_3 = (
        "第三章 质量管理章节文件目录索引及前言部分包含投标人质量控制"
        "和检验流程完整版本独家原创不可复制保留制度规范说明书内容版本"
    )
    _assert_norm_len_at_least(title_1, 50)
    _assert_norm_len_at_least(title_2, 50)
    _assert_norm_len_at_least(title_3, 50)
    paras_a = (
        _mk_chapter(title_1, PLAGIARISM_BODY, 3)
        + _mk_chapter(title_2, PLAGIARISM_BODY, 3)
        + _mk_chapter(title_3, PLAGIARISM_BODY, 3)
    )
    paras_b = list(paras_a)
    pid, bids = await _seed(
        owner_id=seeded_reviewer.id,
        tag="ss_l3",
        bidders_paragraphs=[paras_a, paras_b],
        tender_segment_hashes=None,
    )
    # LLM 全判 plagiarism → 触发铁证(段级 plag 路径)
    llm = ScriptedLLMProvider(
        [
            make_section_similarity_response(
                [(i, "plagiarism") for i in range(30)],
                overall="抄袭",
                confidence="high",
            )
        ],
        loop_last=True,
    )
    await _run_section_sim(pid, bids[0], bids[1], llm)

    pc = await _load_pc(pid, bids[0], bids[1])
    ev = pc.evidence_json
    assert ev["baseline_source"] == "none"
    assert "baseline_unavailable_low_bidder_count" in ev["warnings"]
    # L3 立场:基线缺失 ≠ 信号无效;LLM 判 plag → ironclad 仍触发
    assert pc.is_ironclad is True
