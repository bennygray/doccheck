"""L2 - style Agent 真实检测链路 (C13)

覆盖 tasks.md 11.7~11.8 共 2 Scenario:
1. 3 家 technical 文档 + mock L-8 Stage1/Stage2 全成功 → evidence 3 brief + 1 group
2. Stage1 失败 → skip 哨兵,summary 含 "语言风格分析不可用"
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
from app.services.detect.agents import style as style_mod
from app.services.detect.agents.style_impl.models import (
    GlobalComparison,
    StyleFeatureBrief,
)
from app.services.detect.context import AgentContext

pytestmark = pytest.mark.asyncio


async def _seed(
    seeded_reviewer: User, bidder_names: list[str]
) -> tuple[int, list[int]]:
    async with async_session() as s:
        p = Project(
            name=f"c13-style-p-{id(s)}",
            status="ready",
            owner_id=seeded_reviewer.id,
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)

        bidder_ids = []
        for i, name in enumerate(bidder_names):
            b = Bidder(
                name=name, project_id=p.id, parse_status="extracted"
            )
            s.add(b)
            await s.flush()
            bidder_ids.append(b.id)
            doc = BidDocument(
                bidder_id=b.id,
                file_name=f"{name}.docx",
                file_type="docx",
                file_role="technical",
                file_path=f"/tmp/{name}.docx",
                file_size=1024,
                md5=f"md_{b.id}" + "0" * 26,
                source_archive=f"{name}.zip",
            )
            s.add(doc)
            await s.flush()
            # 多段长段落供 sampler 抽样
            for j in range(10):
                dt = DocumentText(
                    bid_document_id=doc.id,
                    paragraph_index=j,
                    text=f"{name} 技术方案第 {j} 段详细内容 " * 20,
                    location="body",
                )
                s.add(dt)
        await s.commit()
        return p.id, bidder_ids


async def _ctx(project_id, bidder_ids, session):
    bidders = list(
        (
            await session.execute(
                select(Bidder).where(Bidder.id.in_(bidder_ids))
            )
        ).scalars().all()
    )
    return AgentContext(
        project_id=project_id,
        version=1,
        agent_task=None,  # type: ignore[arg-type]
        bidder_a=None,
        bidder_b=None,
        all_bidders=bidders,
        session=session,
        llm_provider=object(),
    )


async def test_s1_full_success(seeded_reviewer, monkeypatch):
    monkeypatch.delenv("STYLE_ENABLED", raising=False)

    async def fake_s1(_provider, bid, _paras, _cfg):
        return StyleFeatureBrief(
            bidder_id=bid,
            **{
                "用词偏好": f"b{bid} 用词",
                "句式特点": "短句",
                "标点习惯": "顿号",
                "段落组织": "总分总",
            },
        )

    async def fake_s2(_provider, _briefs, _cfg):
        return GlobalComparison(  # type: ignore[typeddict-item]
            consistent_groups=[
                {
                    "bidder_ids": list(_briefs.keys())[:2],
                    "consistency_score": 0.85,
                    "typical_features": "共享特征",
                }
            ]
        )

    monkeypatch.setattr("app.services.detect.agents.style.call_l8_stage1", fake_s1)
    monkeypatch.setattr("app.services.detect.agents.style.call_l8_stage2", fake_s2)

    pid, bidders = await _seed(seeded_reviewer, ["甲", "乙", "丙"])
    async with async_session() as s:
        ctx = await _ctx(pid, bidders, s)
        pf = await style_mod.preflight(ctx)
        assert pf.status == "ok"
        result = await style_mod.run(ctx)
        await s.commit()

        ev = result.evidence_json
        assert ev["enabled"] is True
        assert ev["algorithm_version"] == "style_v1"
        assert len(ev["style_features_per_bidder"]) == 3
        assert len(ev["global_comparison"]["consistent_groups"]) == 1
        assert "代写" in ev["limitation_note"]
        assert ev["grouping_strategy"] == "single"
        assert result.score > 0

        oas = (
            await s.execute(
                select(OverallAnalysis).where(
                    OverallAnalysis.project_id == pid,
                    OverallAnalysis.dimension == "style",
                )
            )
        ).scalars().all()
        assert len(oas) == 1


async def test_s2_stage1_failure_skip(seeded_reviewer, monkeypatch):
    monkeypatch.delenv("STYLE_ENABLED", raising=False)

    async def fake_s1_fail(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.services.detect.agents.style.call_l8_stage1", fake_s1_fail
    )

    pid, bidders = await _seed(seeded_reviewer, ["甲", "乙", "丙"])
    async with async_session() as s:
        ctx = await _ctx(pid, bidders, s)
        result = await style_mod.run(ctx)
        await s.commit()

        ev = result.evidence_json
        assert result.score == 0.0
        assert "Stage1" in ev["skip_reason"]
        assert "语言风格分析不可用" in result.summary
