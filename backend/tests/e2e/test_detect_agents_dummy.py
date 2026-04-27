"""L2: 11 Agent 骨架 dummy run (C6 §11.8 + C12 扩展)

验证:
- pair 型 dummy run 写 PairComparison 行
- global 型 dummy run 写 OverallAnalysis 行
- 11 模块加载后注册表 size=11(C12 新增 price_anomaly)
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.bidder import Bidder
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.models.user import User
from app.services.detect import agents  # noqa: F401 - trigger registration
from app.services.detect.context import AgentContext
from app.services.detect.registry import AGENT_REGISTRY

pytestmark = pytest.mark.asyncio


async def test_registry_size_13():
    assert len(AGENT_REGISTRY) == 13


async def test_dummy_pair_run_writes_pair_comparison(
    seeded_reviewer: User,
):
    """text_similarity dummy run → 写 1 行 PairComparison。"""
    async with async_session() as s:
        p = Project(name="ag_p", status="ready", owner_id=seeded_reviewer.id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        b1 = Bidder(name="ag_b1", project_id=p.id, parse_status="identified")
        b2 = Bidder(name="ag_b2", project_id=p.id, parse_status="identified")
        s.add_all([b1, b2])
        await s.commit()
        await s.refresh(b1)
        await s.refresh(b2)

        spec = AGENT_REGISTRY["text_similarity"]
        ctx = AgentContext(
            project_id=p.id,
            version=1,
            agent_task=None,  # dummy run 不读 agent_task
            bidder_a=b1,
            bidder_b=b2,
            all_bidders=[b1, b2],
            session=s,
        )
        result = await spec.run(ctx)
        await s.commit()

        assert 0 <= result.score <= 100
        pcs = (
            await s.execute(
                select(PairComparison).where(
                    PairComparison.project_id == p.id,
                    PairComparison.dimension == "text_similarity",
                )
            )
        ).scalars().all()
        assert len(pcs) == 1


async def test_dummy_global_run_writes_overall_analysis(
    seeded_reviewer: User,
):
    """style dummy run → 写 1 行 OverallAnalysis。"""
    async with async_session() as s:
        p = Project(name="ag_p2", status="ready", owner_id=seeded_reviewer.id)
        s.add(p)
        await s.commit()
        await s.refresh(p)

        spec = AGENT_REGISTRY["style"]
        ctx = AgentContext(
            project_id=p.id,
            version=1,
            agent_task=None,
            bidder_a=None,
            bidder_b=None,
            all_bidders=[],
            session=s,
        )
        result = await spec.run(ctx)
        await s.commit()

        assert 0 <= result.score <= 100
        oas = (
            await s.execute(
                select(OverallAnalysis).where(
                    OverallAnalysis.project_id == p.id,
                    OverallAnalysis.dimension == "style",
                )
            )
        ).scalars().all()
        assert len(oas) == 1
