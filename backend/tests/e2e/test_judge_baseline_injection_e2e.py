"""L2 - judge step5 baseline_resolver 注入 + adjusted dict 透传 + reports API
(detect-tender-baseline §2.10)

验证 judge_and_create_report 的 6 步流程在 detect-tender-baseline §2 改造后:
- step5 调 baseline_resolver.produce_baseline_adjustments → tender_match Adjustment list
- step5 调 _apply_template_adjustments(extra_adjustments=baseline) 合并应用
- AnalysisReport.template_cluster_adjusted_scores.adjustments 含 tender_match 条目
- reports API GET /reports/{v}/dimensions 返回 baseline_source 字段
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.db.session import async_session
from app.main import app
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_metadata import DocumentMetadata
from app.models.document_text import DocumentText
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.models.tender_document import TenderDocument
from app.models.user import User
from app.services.detect import judge_llm
from app.services.detect.judge import judge_and_create_report

pytestmark = pytest.mark.asyncio


# ============================================================ Seeders


async def _seed_baseline_scenario(
    tag: str,
    *,
    n_bidders: int = 3,
    tender_hashes: list[str] | None = None,
    pc_segment_hashes_per_bidder: dict[str, list[str]] | None = None,
    pc_score: float = 88.0,
    pc_iron: bool = True,
) -> tuple[int, int, list[int]]:
    """构造 project + N 投标方 + 各自 BidDocument/DocumentText(段级 hash) +
    可选 TenderDocument(段级 hash 集合) + text_similarity PCs(score+iron 可控)。

    Args:
        tag: 测试 tag,串入 user/project name 作隔离 key
        n_bidders: 投标方数量
        tender_hashes: TenderDocument.segment_hashes;None 则不建 tender(L2/L3 路径)
        pc_segment_hashes_per_bidder: {bidder_letter: [hash, ...]} 控制每家段 hash 集合
        pc_score / pc_iron: 每个 text_similarity PC 的初始 raw score / iron

    Returns:
        (project_id, version, list[pc_id])
    """
    pc_ids: list[int] = []

    async with async_session() as s:
        user = User(
            username=f"baseline_{tag}",
            password_hash="x" * 60,
            role="reviewer",
            login_fail_count=0,
        )
        s.add(user)
        await s.flush()
        project = Project(
            name=f"P_baseline_{tag}",
            owner_id=user.id,
            status="analyzing",
        )
        s.add(project)
        await s.flush()

        bidders: list[Bidder] = []
        letters = ["A", "B", "C", "D", "E"][:n_bidders]
        for letter in letters:
            b = Bidder(
                name=f"{letter}_{tag}",
                project_id=project.id,
                parse_status="extracted",
            )
            s.add(b)
            bidders.append(b)
        await s.flush()

        # 每个 bidder 一份 technical docx
        bid_docs: dict[str, BidDocument] = {}
        for letter, b in zip(letters, bidders, strict=True):
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
            bid_docs[letter] = doc
        await s.flush()

        # 每个 bidder 几条 DocumentText 带 segment_hash
        if pc_segment_hashes_per_bidder:
            for letter, hashes in pc_segment_hashes_per_bidder.items():
                if letter not in bid_docs:
                    continue
                for i, h in enumerate(hashes):
                    s.add(
                        DocumentText(
                            bid_document_id=bid_docs[letter].id,
                            paragraph_index=i,
                            text=f"段落{letter}{i}",
                            location="body",
                            segment_hash=h,
                        )
                    )

        # 可选 TenderDocument
        if tender_hashes is not None:
            tender = TenderDocument(
                project_id=project.id,
                file_name="招标文件.zip",
                file_path=f"/tmp/tender_{tag}.zip",
                file_size=2048,
                md5="t" * 32,
                parse_status="extracted",
                segment_hashes=tender_hashes,
                boq_baseline_hashes=[],
            )
            s.add(tender)
            await s.flush()

        version = 1

        # AgentTask 信号 + 非信号一律 succeeded(满足 _has_sufficient_evidence)
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
            is_pair = an in {
                "text_similarity",
                "section_similarity",
                "structure_similarity",
                "metadata_author",
                "metadata_time",
                "metadata_machine",
                "price_consistency",
            }
            s.add(
                AgentTask(
                    project_id=project.id,
                    version=version,
                    agent_name=an,
                    agent_type="pair" if is_pair else "global",
                    pair_bidder_a_id=bidders[0].id if is_pair else None,
                    pair_bidder_b_id=bidders[1].id if is_pair else None,
                    status="succeeded",
                    score=Decimal("50"),
                )
            )

        # text_similarity PCs:全 (a, b) 对
        for i, ba in enumerate(bidders):
            for bb in bidders[i + 1 :]:
                pc = PairComparison(
                    project_id=project.id,
                    version=version,
                    bidder_a_id=ba.id,
                    bidder_b_id=bb.id,
                    dimension="text_similarity",
                    score=Decimal(str(pc_score)),
                    is_ironclad=pc_iron,
                    evidence_json={},
                )
                s.add(pc)
                await s.flush()
                pc_ids.append(pc.id)

        # 必要 OA(满足 _has_sufficient_evidence:至少一个 SIGNAL OA)
        s.add(
            OverallAnalysis(
                project_id=project.id,
                version=version,
                dimension="error_consistency",
                score=Decimal("50"),
                evidence_json={"has_iron_evidence": False},
            )
        )

        await s.commit()
        return project.id, version, pc_ids


async def _cleanup(tag_prefix: str = "baseline_") -> None:
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
                    delete(DocumentText).where(
                        DocumentText.bid_document_id.in_(doc_ids)
                    )
                )
                await s.execute(
                    delete(DocumentMetadata).where(
                        DocumentMetadata.bid_document_id.in_(doc_ids)
                    )
                )
                await s.execute(
                    delete(BidDocument).where(BidDocument.id.in_(doc_ids))
                )
            await s.execute(
                delete(TenderDocument).where(
                    TenderDocument.project_id.in_(project_ids)
                )
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
async def clean_baseline():
    await _cleanup()
    yield
    await _cleanup()


# ============================================================ Tests


async def test_l1_tender_match_produces_adjustments(
    clean_baseline, monkeypatch
) -> None:
    """L1 tender 命中场景 → judge step5 调 baseline_resolver,产 tender_match
    Adjustment;AnalysisReport.template_cluster_adjusted_scores.adjustments
    包含 reason='tender_match' + baseline_source='tender'。"""
    tender_h = ["h_tender_1", "h_tender_2"]
    pid, version, pc_ids = await _seed_baseline_scenario(
        "l1_tender_hit",
        n_bidders=3,
        tender_hashes=tender_h,
        pc_segment_hashes_per_bidder={
            "A": ["h_tender_1"],
            "B": ["h_tender_1"],
            "C": ["h_tender_1"],
        },
        pc_score=88.0,
        pc_iron=True,
    )

    async def _mock_llm(*args, **kwargs):
        return "baseline 命中,综合判低风险", 30.0

    monkeypatch.setattr(judge_llm, "call_llm_judge", _mock_llm)

    await judge_and_create_report(pid, version)

    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()

    assert report.template_cluster_adjusted_scores is not None
    js = report.template_cluster_adjusted_scores
    pc_adjs = [a for a in js["adjustments"] if a["scope"] == "pc"]
    tender_adjs = [a for a in pc_adjs if a["reason"] == "tender_match"]
    assert len(tender_adjs) == 3, f"expected 3 tender_match, got {tender_adjs}"
    assert all(a["baseline_source"] == "tender" for a in tender_adjs)
    assert all(a["adjusted_score"] == 0.0 for a in tender_adjs)

    # template_cluster_detected = bool(clusters);本场景无 metadata cluster → False
    assert report.template_cluster_detected is False


async def test_no_tender_no_consensus_no_adjustments(
    clean_baseline, monkeypatch
) -> None:
    """无 tender + 3 bidders + 段 hash 各异(无共识)→ baseline 无产出 →
    AnalysisReport.template_cluster_adjusted_scores=None。"""
    pid, version, pc_ids = await _seed_baseline_scenario(
        "no_baseline",
        n_bidders=3,
        tender_hashes=None,
        pc_segment_hashes_per_bidder={
            "A": ["h_a"],
            "B": ["h_b"],
            "C": ["h_c"],
        },
        pc_score=80.0,
        pc_iron=False,
    )

    async def _mock_llm(*args, **kwargs):
        return "无 baseline", 30.0

    monkeypatch.setattr(judge_llm, "call_llm_judge", _mock_llm)

    await judge_and_create_report(pid, version)

    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()

    assert report.template_cluster_adjusted_scores is None
    assert report.template_cluster_detected is False


async def test_l2_consensus_match_produces_adjustments(
    clean_baseline, monkeypatch
) -> None:
    """无 tender + 3 bidders 同段 hash → consensus_match Adjustment。"""
    consensus_h = "h_consensus_1"
    pid, version, pc_ids = await _seed_baseline_scenario(
        "l2_consensus_hit",
        n_bidders=3,
        tender_hashes=None,
        pc_segment_hashes_per_bidder={
            "A": [consensus_h],
            "B": [consensus_h],
            "C": [consensus_h],
        },
        pc_score=85.0,
        pc_iron=False,
    )

    async def _mock_llm(*args, **kwargs):
        return "consensus 命中", 30.0

    monkeypatch.setattr(judge_llm, "call_llm_judge", _mock_llm)

    await judge_and_create_report(pid, version)

    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()

    assert report.template_cluster_adjusted_scores is not None
    js = report.template_cluster_adjusted_scores
    pc_adjs = [a for a in js["adjustments"] if a["scope"] == "pc"]
    consensus_adjs = [a for a in pc_adjs if a["reason"] == "consensus_match"]
    assert len(consensus_adjs) == 3, (
        f"expected 3 consensus_match, got {consensus_adjs}"
    )
    assert all(a["baseline_source"] == "consensus" for a in consensus_adjs)


async def test_l3_two_bidders_no_adjustments(
    clean_baseline, monkeypatch
) -> None:
    """无 tender + 2 bidders → baseline 不产 Adjustment(L3 不抑制 ironclad)。"""
    pid, version, pc_ids = await _seed_baseline_scenario(
        "l3_low_bidders",
        n_bidders=2,
        tender_hashes=None,
        pc_segment_hashes_per_bidder={
            "A": ["h1"],
            "B": ["h1"],  # 即使 hash 相同,2 家 < 共识门槛
        },
        pc_score=85.0,
        pc_iron=True,
    )

    async def _mock_llm(*args, **kwargs):
        return "L3 警示", 50.0

    monkeypatch.setattr(judge_llm, "call_llm_judge", _mock_llm)

    await judge_and_create_report(pid, version)

    async with async_session() as s:
        report = (
            await s.execute(
                select(AnalysisReport).where(AnalysisReport.project_id == pid)
            )
        ).scalar_one()

    # L3 → baseline_resolver 返空 excluded_pair_ids → 无 Adjustment
    if report.template_cluster_adjusted_scores is not None:
        pc_adjs = [
            a
            for a in report.template_cluster_adjusted_scores.get("adjustments", [])
            if a["scope"] == "pc"
        ]
        baseline_adjs = [
            a
            for a in pc_adjs
            if a["reason"] in {"tender_match", "consensus_match"}
        ]
        assert baseline_adjs == [], f"L3 should not produce baseline adjustments"


async def test_reports_api_includes_baseline_source(
    seeded_reviewer, reviewer_token, clean_baseline, monkeypatch
) -> None:
    """reports API GET /reports/{v}/dimensions 响应 schema 含 baseline_source。
    L1 tender 命中场景下,该字段从 AnalysisReport.template_cluster_adjusted_scores
    反推为 'tender'(detector §3+ 时改为直接读 PC.evidence_json)。"""
    tender_h = ["h_t1"]
    pid, version, _ = await _seed_baseline_scenario(
        "api_tender",
        n_bidders=3,
        tender_hashes=tender_h,
        pc_segment_hashes_per_bidder={
            "A": ["h_t1"],
            "B": ["h_t1"],
            "C": ["h_t1"],
        },
        pc_score=88.0,
        pc_iron=False,
    )

    # 把 project owner 改为 seeded_reviewer 让 reviewer_token 可见
    async with async_session() as s:
        proj = await s.get(Project, pid)
        proj.owner_id = seeded_reviewer.id
        await s.commit()

    async def _mock_llm(*args, **kwargs):
        return "tender 命中", 30.0

    monkeypatch.setattr(judge_llm, "call_llm_judge", _mock_llm)

    await judge_and_create_report(pid, version)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/projects/{pid}/reports/{version}/dimensions",
            headers={"Authorization": f"Bearer {reviewer_token}"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    dims = {d["dimension"]: d for d in body["dimensions"]}
    text_dim = dims["text_similarity"]
    # API schema 含 baseline_source 字段,且 text_similarity 维度
    # 因 tender_match adjustment 反推 → "tender"
    assert "baseline_source" in text_dim
    assert text_dim["baseline_source"] == "tender", text_dim
    # warnings 字段也应存在(老兼容默认空)
    assert "warnings" in text_dim
