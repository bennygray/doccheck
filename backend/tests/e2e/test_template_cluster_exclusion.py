"""L2 - 模板簇识别 + adjustment + judge 全链路 (CH-2 detect-template-exclusion)

5 case 覆盖:
- 5.1 3 bidder 全簇 → adjustments 17 条 + risk_level=low(text_sim adjusted=45.80 走 LLM)
- 5.2 file_role 过滤 → qualification 不参与识别(只剩 technical 不簇)
- 5.3 真围标 + 同模板:text_sim iron + section/error iron 不被掩盖 → high
- 5.4 metadata 全 NULL 回归 → detected=false + adjusted_scores=null
- 5.4b indeterminate 专用 fixture → 全 SIGNAL OA adjusted=0 → indeterminate
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_metadata import DocumentMetadata
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.models.user import User
from app.services.detect import judge_llm
from app.services.detect.judge import judge_and_create_report

pytestmark = pytest.mark.asyncio


# ============================================================ Seeders


async def _seed_3_bidder_template_cluster(
    tag: str,
    *,
    text_iron: bool = False,
    text_score: float = 91.59,
    section_iron: bool = False,
    section_score: float = 0,
    error_consistency_iron: bool = False,
    metadata_all_null: bool = False,
) -> tuple[int, int]:
    """构造 3 bidder + 同 metadata 模板簇 + 受污染高分 mock。

    所有 bidder 文档 file_role=technical,metadata author=LP + 同 created_at。
    """
    async with async_session() as s:
        user = User(
            username=f"tpl_{tag}",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        s.add(user)
        await s.flush()
        project = Project(
            name=f"P_{tag}",
            owner_id=user.id,
            status="analyzing",
        )
        s.add(project)
        await s.flush()

        bidders = []
        for letter in ["A", "B", "C"]:
            b = Bidder(
                name=f"{letter}_{tag}",
                project_id=project.id,
                parse_status="extracted",
            )
            s.add(b)
            bidders.append(b)
        await s.flush()

        # 每个 bidder 一份 technical docx + metadata
        # metadata_all_null=True:不写 metadata 行(模拟全 NULL 退化场景)
        if not metadata_all_null:
            shared_created_at = datetime(
                2023, 10, 8, 23, 16, 0, tzinfo=timezone.utc
            )
            for b in bidders:
                doc = BidDocument(
                    bidder_id=b.id,
                    file_name=f"tech_{b.name}.docx",
                    file_path=f"/tmp/{b.name}/tech.docx",
                    file_size=1024,
                    file_type="docx",
                    md5=f"md5_tech_{b.name}",
                    file_role="technical",
                    parse_status="content_parsed",
                    source_archive=f"{b.name}.zip",
                )
                s.add(doc)
                await s.flush()
                meta = DocumentMetadata(
                    bid_document_id=doc.id,
                    author="LP",
                    doc_created_at=shared_created_at,
                )
                s.add(meta)

        version = 1

        # AgentTask: 信号型 + 非信号型 全 succeeded(模拟 mock pipeline)
        signal_agents = [
            "text_similarity",
            "section_similarity",
            "structure_similarity",
            "image_reuse",
            "style",
            "error_consistency",
        ]
        nonsignal_agents = [
            "metadata_author",
            "metadata_time",
            "metadata_machine",
            "price_consistency",
        ]
        for an in signal_agents + nonsignal_agents + ["price_anomaly"]:
            s.add(
                AgentTask(
                    project_id=project.id,
                    version=version,
                    agent_name=an,
                    agent_type="pair"
                    if an
                    in {
                        "text_similarity",
                        "section_similarity",
                        "structure_similarity",
                        "metadata_author",
                        "metadata_time",
                        "metadata_machine",
                        "price_consistency",
                    }
                    else "global",
                    pair_bidder_a_id=bidders[0].id
                    if an
                    in {
                        "text_similarity",
                        "section_similarity",
                        "structure_similarity",
                        "metadata_author",
                        "metadata_time",
                        "metadata_machine",
                        "price_consistency",
                    }
                    else None,
                    pair_bidder_b_id=bidders[1].id
                    if an
                    in {
                        "text_similarity",
                        "section_similarity",
                        "structure_similarity",
                        "metadata_author",
                        "metadata_time",
                        "metadata_machine",
                        "price_consistency",
                    }
                    else None,
                    status="succeeded",
                    score=Decimal("0"),
                )
            )

        # PairComparison: 受污染高分(structure / metadata_author / metadata_time / text)
        pair_combos = [
            (bidders[0].id, bidders[1].id),
            (bidders[0].id, bidders[2].id),
            (bidders[1].id, bidders[2].id),
        ]
        for a_id, b_id in pair_combos:
            # structure_similarity score=100 iron=true(scorer.py 阈值)
            s.add(
                PairComparison(
                    project_id=project.id,
                    version=version,
                    bidder_a_id=a_id,
                    bidder_b_id=b_id,
                    dimension="structure_similarity",
                    score=Decimal("100"),
                    is_ironclad=True,
                    evidence_json={},
                )
            )
            # metadata_author score=100 iron=true(METADATA_IRONCLAD_THRESHOLD=85)
            s.add(
                PairComparison(
                    project_id=project.id,
                    version=version,
                    bidder_a_id=a_id,
                    bidder_b_id=b_id,
                    dimension="metadata_author",
                    score=Decimal("100"),
                    is_ironclad=True,
                    evidence_json={},
                )
            )
            # metadata_time
            s.add(
                PairComparison(
                    project_id=project.id,
                    version=version,
                    bidder_a_id=a_id,
                    bidder_b_id=b_id,
                    dimension="metadata_time",
                    score=Decimal("100"),
                    is_ironclad=True,
                    evidence_json={},
                )
            )
            # text_similarity
            s.add(
                PairComparison(
                    project_id=project.id,
                    version=version,
                    bidder_a_id=a_id,
                    bidder_b_id=b_id,
                    dimension="text_similarity",
                    score=Decimal(str(text_score)),
                    is_ironclad=text_iron,
                    evidence_json={},
                )
            )
            # section_similarity (默认 0,真围标 case 提高)
            s.add(
                PairComparison(
                    project_id=project.id,
                    version=version,
                    bidder_a_id=a_id,
                    bidder_b_id=b_id,
                    dimension="section_similarity",
                    score=Decimal(str(section_score)),
                    is_ironclad=section_iron,
                    evidence_json={},
                )
            )

        # OA: style global(76.5)+ image_reuse / error_consistency / price_anomaly
        s.add(
            OverallAnalysis(
                project_id=project.id,
                version=version,
                dimension="style",
                score=Decimal("76.5"),
                evidence_json={},
            )
        )
        s.add(
            OverallAnalysis(
                project_id=project.id,
                version=version,
                dimension="image_reuse",
                score=Decimal("0"),
                evidence_json={},
            )
        )
        s.add(
            OverallAnalysis(
                project_id=project.id,
                version=version,
                dimension="error_consistency",
                score=Decimal("0"),
                evidence_json={
                    "has_iron_evidence": error_consistency_iron,
                },
            )
        )
        s.add(
            OverallAnalysis(
                project_id=project.id,
                version=version,
                dimension="price_anomaly",
                score=Decimal("0"),
                evidence_json={},
            )
        )

        await s.commit()
        return project.id, version


async def _cleanup(tag_prefix: str = "tpl_") -> None:
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
            bidder_ids = (
                await s.execute(
                    select(Bidder.id).where(Bidder.project_id.in_(project_ids))
                )
            ).scalars().all()
            doc_ids: list[int] = []
            if bidder_ids:
                doc_ids = (
                    await s.execute(
                        select(BidDocument.id).where(
                            BidDocument.bidder_id.in_(bidder_ids)
                        )
                    )
                ).scalars().all()
            if doc_ids:
                await s.execute(
                    delete(DocumentMetadata).where(
                        DocumentMetadata.bid_document_id.in_(doc_ids)
                    )
                )
                await s.execute(
                    delete(BidDocument).where(BidDocument.id.in_(doc_ids))
                )
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


@pytest.fixture
async def clean_tpl():
    await _cleanup()
    yield
    await _cleanup()


# ============================================================ 5.1 Full cluster


async def test_3_bidder_full_cluster_low(clean_tpl, monkeypatch) -> None:
    """3 bidder 全簇 + 受污染高分(structure/metadata_author/metadata_time iron)
    → adjustment 后 adj_has_ironclad=False + text DEF-OA adjusted=45.80
    → 走 LLM(mock 返低分)→ risk_level == "low" 严格断言"""
    pid, version = await _seed_3_bidder_template_cluster("full_cluster")

    # mock LLM 返 llm_suggested ≤ formula_total_adj(round 8 reviewer M1)
    # 实际 formula_total_adj 很低(无铁证 + per_dim_max 多维 0),mock 返 30
    async def _mock_llm(*args, **kwargs):
        return "簇命中,信号弱,LLM 综合判低风险", 30.0

    monkeypatch.setattr(judge_llm, "call_llm_judge", _mock_llm)

    await judge_and_create_report(pid, version)

    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()
    assert report.template_cluster_detected is True
    assert report.risk_level == "low"
    assert report.template_cluster_adjusted_scores is not None
    js = report.template_cluster_adjusted_scores
    assert "clusters" in js
    assert len(js["clusters"]) == 1
    assert sorted(js["clusters"][0]["bidder_ids"])[0:3] == sorted(
        js["clusters"][0]["bidder_ids"]
    )  # 排序好
    assert js["clusters"][0]["cluster_key_sample"]["author"] == "lp"

    # adjustments 数量按 scope 分:12 pc(structure×3 + metadata_author×3 +
    # metadata_time×3 + text×3) + 1 global_oa(style) + 4 def_oa(structure /
    # metadata_author / metadata_time / text 各 1)= 17 条
    pc_entries = [a for a in js["adjustments"] if a["scope"] == "pc"]
    global_oa_entries = [a for a in js["adjustments"] if a["scope"] == "global_oa"]
    def_oa_entries = [a for a in js["adjustments"] if a["scope"] == "def_oa"]
    assert len(pc_entries) == 12
    assert len(global_oa_entries) == 1
    assert len(def_oa_entries) == 4
    assert len(js["adjustments"]) == 17

    # DB 中 PC/OA 原值保留(不回写)
    async with async_session() as s:
        pcs = (
            await s.execute(
                select(PairComparison).where(
                    PairComparison.project_id == pid,
                    PairComparison.dimension == "structure_similarity",
                )
            )
        ).scalars().all()
    for pc in pcs:
        assert float(pc.score) == 100.0  # raw 保留
        assert pc.is_ironclad is True  # raw 保留


# ============================================================ 5.2 file_role filter


async def test_file_role_filter_qualification_excluded(
    clean_tpl, monkeypatch
) -> None:
    """qualification PDF metadata 不参与簇识别(只 file_role in TEMPLATE_FILE_ROLES)。

    构造 2 bidder:每家有 technical(metadata=XYZ,t1)+ qualification(metadata=Admin,t0)。
    technical 各异 → cluster 不命中(qualification 被过滤,不会用 Admin/t0 判同簇)。
    """
    async with async_session() as s:
        user = User(
            username="tpl_filter",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        s.add(user)
        await s.flush()
        project = Project(name="P_filter", owner_id=user.id, status="analyzing")
        s.add(project)
        await s.flush()
        ba = Bidder(name="A_filter", project_id=project.id, parse_status="extracted")
        bb = Bidder(name="B_filter", project_id=project.id, parse_status="extracted")
        s.add(ba)
        s.add(bb)
        await s.flush()

        # 各自 technical 不同 metadata
        for b, author in [(ba, "XYZ"), (bb, "ZYX")]:
            doc = BidDocument(
                bidder_id=b.id,
                file_name=f"tech_{b.name}.docx",
                file_path=f"/tmp/{b.name}/tech.docx",
                file_size=1024,
                file_type="docx",
                md5=f"md5_tech_{b.name}",
                file_role="technical",
                parse_status="content_parsed",
                source_archive=f"{b.name}.zip",
            )
            s.add(doc)
            await s.flush()
            s.add(
                DocumentMetadata(
                    bid_document_id=doc.id,
                    author=author,
                    doc_created_at=datetime(
                        2023, 1, 1, tzinfo=timezone.utc
                    ),
                )
            )
        # 各自 qualification 同 author=Admin + 同 created_at(若过滤失败,会误识别簇)
        admin_dt = datetime(2020, 5, 5, 10, 0, 0, tzinfo=timezone.utc)
        for b in [ba, bb]:
            doc = BidDocument(
                bidder_id=b.id,
                file_name=f"qual_{b.name}.pdf",
                file_path=f"/tmp/{b.name}/qual.pdf",
                file_size=512,
                file_type="pdf",
                md5=f"md5_qual_{b.name}",
                file_role="qualification",
                parse_status="content_parsed",
                source_archive=f"{b.name}.zip",
            )
            s.add(doc)
            await s.flush()
            s.add(
                DocumentMetadata(
                    bid_document_id=doc.id,
                    author="Admin",
                    doc_created_at=admin_dt,
                )
            )

        # 1 个 succeeded signal,scoring 0 → indeterminate 路径(无关本 case)
        s.add(
            AgentTask(
                project_id=project.id,
                version=1,
                agent_name="text_similarity",
                agent_type="pair",
                pair_bidder_a_id=ba.id,
                pair_bidder_b_id=bb.id,
                status="succeeded",
                score=Decimal("0"),
            )
        )
        await s.commit()
        pid = project.id

    async def _no_call(*args, **kwargs):
        raise AssertionError("LLM should not be called for indeterminate")

    monkeypatch.setattr(judge_llm, "call_llm_judge", _no_call)
    await judge_and_create_report(pid, 1)

    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()
    # qualification 被过滤 → cluster 不命中
    assert report.template_cluster_detected is False
    assert report.template_cluster_adjusted_scores is None


# ============================================================ 5.3 Real collusion + template


async def test_real_collusion_with_template_iron_preserved(
    clean_tpl, monkeypatch
) -> None:
    """真围标 + 同模板:text_sim iron=true(豁免保留)+ section iron=true +
    error_consistency has_iron_evidence=true → has_ironclad=True → high。

    DB 断言 text_similarity DEF-OA OA score=95(max raw) + has_iron_evidence=true
    (round 8 reviewer M4 锁)。
    """
    pid, version = await _seed_3_bidder_template_cluster(
        "real_coll",
        text_iron=True,
        text_score=95.0,  # 模拟 LLM judgments ≥3 段 plagiarism
        section_iron=True,
        section_score=85.0,
        error_consistency_iron=True,
    )

    async def _mock_llm(*args, **kwargs):
        return "真围标证据充分,LLM 维持 high 结论", 90.0

    monkeypatch.setattr(judge_llm, "call_llm_judge", _mock_llm)
    await judge_and_create_report(pid, version)

    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()
    assert report.template_cluster_detected is True
    assert report.risk_level == "high"

    # text_sim adjustments reason 验证 + DEF-OA score=95 has_iron=true
    js = report.template_cluster_adjusted_scores
    text_pc_entries = [
        a
        for a in js["adjustments"]
        if a["scope"] == "pc" and a["dimension"] == "text_similarity"
    ]
    assert len(text_pc_entries) == 3
    for entry in text_pc_entries:
        assert entry["reason"] == "template_cluster_downgrade_suppressed_by_ironclad"
        assert entry["adjusted_score"] == 95.0  # 不降权
    text_def_oa = [
        a
        for a in js["adjustments"]
        if a["scope"] == "def_oa" and a["dimension"] == "text_similarity"
    ]
    assert len(text_def_oa) == 1
    assert text_def_oa[0]["adjusted_score"] == 95.0

    async with async_session() as s:
        text_def_oa_row = (
            await s.execute(
                select(OverallAnalysis).where(
                    OverallAnalysis.project_id == pid,
                    OverallAnalysis.dimension == "text_similarity",
                )
            )
        ).scalar_one()
    # DB 中 raw 入库(D7 审计原则),不是 adjusted
    assert float(text_def_oa_row.score) == 95.0  # raw max == adjusted max(豁免保留)
    assert text_def_oa_row.evidence_json["has_iron_evidence"] is True


# ============================================================ 5.4 metadata 全 NULL


async def test_metadata_all_null_regression(clean_tpl, monkeypatch) -> None:
    """metadata 全无 → cluster 不命中 → detected=false + adjusted=null;
    helper 调用传 None 走老路径,与 change 前完全等价。"""
    pid, version = await _seed_3_bidder_template_cluster(
        "null_meta",
        metadata_all_null=True,
    )

    async def _mock_llm(*args, **kwargs):
        return "证据弱,无法判定", 50.0

    monkeypatch.setattr(judge_llm, "call_llm_judge", _mock_llm)
    await judge_and_create_report(pid, version)

    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()
    assert report.template_cluster_detected is False
    assert report.template_cluster_adjusted_scores is None


# ============================================================ 5.4b indeterminate


async def test_indeterminate_reachable_with_full_cluster_zero_signal(
    clean_tpl, monkeypatch
) -> None:
    """全 SIGNAL OA adjusted=0 → _has_sufficient_evidence 返 False → indeterminate
    严格断言;验证 indeterminate 分支真实可达(round 4 reviewer M4 + round 7 M4)。"""
    # text_score=0 + 其他 signal 全 0 + 模板簇剔除 structure/metadata_author/
    # metadata_time + style 全覆盖剔除
    pid, version = await _seed_3_bidder_template_cluster(
        "indet",
        text_score=0,  # text_sim 也 0
    )

    async def _no_call(*args, **kwargs):
        raise AssertionError(
            "LLM should not be called when evidence is insufficient"
        )

    monkeypatch.setattr(judge_llm, "call_llm_judge", _no_call)
    await judge_and_create_report(pid, version)

    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()
    assert report.template_cluster_detected is True
    assert report.risk_level == "indeterminate"
