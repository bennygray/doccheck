"""L2 - error_consistency Agent 真实检测链路 (C13)

覆盖 tasks.md 11.1~11.4 共 4 Scenario:
1. 3 家 identity_info 完整,mock L-5 返铁证 → has_iron_evidence=true
2. 1 家缺 identity_info → preflight downgrade(贴 spec 任一缺)
3. 全部 identity_info=None → preflight downgrade,is_iron_evidence 强制 False
4. ENABLED=false → evidence.enabled=false

策略:手工构造 ctx 直调 Agent.run() / preflight(不走 engine)。
LLM 通过 monkeypatch 拦截 error_consistency.call_l5 直接返 mock 判断。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_text import DocumentText
from app.models.overall_analysis import OverallAnalysis
from app.models.project import Project
from app.models.user import User
from app.services.detect.agents import error_consistency as ec_mod
from app.services.detect.agents.error_impl.models import LLMJudgment
from app.services.detect.context import AgentContext

pytestmark = pytest.mark.asyncio


async def _seed(
    seeded_reviewer: User, bidder_specs: list[tuple[str, dict | None]]
) -> tuple[int, list[int]]:
    """建 project + 多 bidder + 每 bidder 一份 technical 文档含一段正文。

    bidder_specs: [(name, identity_info), ...]
    返 (project_id, [bidder_id...]).
    """
    async with async_session() as s:
        p = Project(
            name=f"c13-ec-p-{id(s)}",
            status="ready",
            owner_id=seeded_reviewer.id,
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)

        bidder_ids: list[int] = []
        for name, identity in bidder_specs:
            b = Bidder(
                name=name,
                project_id=p.id,
                parse_status="extracted",
                identity_info=identity,
            )
            s.add(b)
            await s.flush()
            bidder_ids.append(b.id)
            doc = BidDocument(
                bidder_id=b.id,
                file_name=f"{name}_技术方案.docx",
                file_type="docx",
                file_role="technical",
                file_path=f"/tmp/{name}.docx",
                file_size=1024,
                md5=f"md5_{b.id}_{name[:4]}" + "0" * 20,
                source_archive=f"{name}.zip",
            )
            s.add(doc)
            await s.flush()
            # 每 bidder 一段含另一个 bidder 公司名的正文(制造交叉命中)
            other_names = [
                specs[0] for specs in bidder_specs if specs[0] != name
            ]
            text = "技术方案正文:涉及 " + " ".join(other_names)
            dt = DocumentText(
                bid_document_id=doc.id,
                paragraph_index=0,
                text=text,
                location="body",
            )
            s.add(dt)
        await s.commit()
        return p.id, bidder_ids


async def _ctx(
    project_id: int, bidder_ids: list[int], session, *, downgrade=False
) -> AgentContext:
    bidders_stmt = select(Bidder).where(Bidder.id.in_(bidder_ids))
    bidders = list((await session.execute(bidders_stmt)).scalars().all())
    return AgentContext(
        project_id=project_id,
        version=1,
        agent_task=None,  # type: ignore[arg-type]
        bidder_a=None,
        bidder_b=None,
        all_bidders=bidders,
        session=session,
        llm_provider=object(),  # non-None 让 run 走 LLM 路径(被 monkeypatch 拦)
        downgrade=downgrade,
    )


# ---------- Scenario 1: 全 identity 完整 + L-5 铁证 → has_iron_evidence ----------


async def test_s1_iron_evidence_hit(seeded_reviewer, monkeypatch):
    monkeypatch.delenv("ERROR_CONSISTENCY_ENABLED", raising=False)

    async def fake_call_l5(_provider, _segs, _a, _b, _cfg):
        return LLMJudgment(
            is_cross_contamination=True,
            direct_evidence=True,
            confidence=0.9,
            evidence=[],
        )

    monkeypatch.setattr(
        "app.services.detect.agents.error_consistency.call_l5", fake_call_l5
    )

    pid, bidders = await _seed(
        seeded_reviewer,
        [
            ("甲建设公司", {"company_name": "甲建设公司"}),
            ("乙建设公司", {"company_name": "乙建设公司"}),
            ("丙建设公司", {"company_name": "丙建设公司"}),
        ],
    )
    async with async_session() as s:
        ctx = await _ctx(pid, bidders, s)
        pf = await ec_mod.preflight(ctx)
        assert pf.status == "ok"
        result = await ec_mod.run(ctx)
        await s.commit()

        ev = result.evidence_json
        assert ev["algorithm_version"] == "error_consistency_v1"
        assert ev["enabled"] is True
        assert ev["downgrade_mode"] is False
        assert ev["has_iron_evidence"] is True
        assert len(ev["pair_results"]) > 0
        assert any(p["is_iron_evidence"] for p in ev["pair_results"])

        # OverallAnalysis 落一行
        oas = (
            await s.execute(
                select(OverallAnalysis).where(
                    OverallAnalysis.project_id == pid,
                    OverallAnalysis.dimension == "error_consistency",
                )
            )
        ).scalars().all()
        assert len(oas) == 1


# ---------- Scenario 2: 1 家缺 → preflight downgrade(spec 原语义) ----------


async def test_s2_partial_missing_preflight_downgrade(seeded_reviewer):
    pid, bidders = await _seed(
        seeded_reviewer,
        [
            ("甲建设公司", {"company_name": "甲建设公司"}),
            ("乙建设公司", None),  # 缺
            ("丙建设公司", {"company_name": "丙建设公司"}),
        ],
    )
    async with async_session() as s:
        ctx = await _ctx(pid, bidders, s)
        pf = await ec_mod.preflight(ctx)
    assert pf.status == "downgrade"


# ---------- Scenario 3: 全缺 → preflight downgrade + run 不铁证 ----------


async def test_s3_all_missing_downgrade_no_iron(seeded_reviewer, monkeypatch):
    async def fake_call_l5(_provider, _segs, _a, _b, _cfg):
        # 即使 mock 返铁证
        return LLMJudgment(
            is_cross_contamination=True,
            direct_evidence=True,
            confidence=0.9,
            evidence=[],
        )

    monkeypatch.setattr(
        "app.services.detect.agents.error_consistency.call_l5", fake_call_l5
    )

    pid, bidders = await _seed(
        seeded_reviewer,
        [("甲公司", None), ("乙公司", None), ("丙公司", None)],
    )
    async with async_session() as s:
        ctx = await _ctx(pid, bidders, s, downgrade=True)
        result = await ec_mod.run(ctx)
        await s.commit()

        ev = result.evidence_json
        assert ev["downgrade_mode"] is True
        # 降级模式强制不铁证
        assert ev["has_iron_evidence"] is False


# ---------- Scenario 4: ENABLED=false ----------


async def test_s4_disabled(seeded_reviewer, monkeypatch):
    monkeypatch.setenv("ERROR_CONSISTENCY_ENABLED", "false")

    pid, bidders = await _seed(
        seeded_reviewer,
        [
            ("甲建设公司", {"company_name": "甲建设公司"}),
            ("乙建设公司", {"company_name": "乙建设公司"}),
        ],
    )
    async with async_session() as s:
        ctx = await _ctx(pid, bidders, s)
        result = await ec_mod.run(ctx)
        await s.commit()

        ev = result.evidence_json
        assert ev["enabled"] is False
        assert result.score == 0.0
