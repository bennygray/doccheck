"""L2 - image_reuse Agent 真实检测链路 (C13)

覆盖 tasks.md 11.5~11.6 共 2 Scenario:
1. 3 家 bidder,2 张 md5 相同 + 1 对 phash 距离 3 → OverallAnalysis 落 1 行
2. 全部小图过滤后 0 张 → skip 哨兵 score=0
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_image import DocumentImage
from app.models.overall_analysis import OverallAnalysis
from app.models.project import Project
from app.models.user import User
from app.services.detect.agents import image_reuse as ir_mod
from app.services.detect.context import AgentContext

pytestmark = pytest.mark.asyncio


def _hex(base: str = "ff") -> str:
    return base.ljust(16, "0")[:16]


async def _seed(
    seeded_reviewer: User,
    bidder_images: list[list[tuple[str, str, int, int]]],
    # [(md5, phash, width, height), ...]
) -> tuple[int, list[int]]:
    async with async_session() as s:
        p = Project(
            name=f"c13-ir-p-{id(s)}",
            status="ready",
            owner_id=seeded_reviewer.id,
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)

        bidder_ids = []
        for i, imgs in enumerate(bidder_images):
            b = Bidder(
                name=f"B{i}",
                project_id=p.id,
                parse_status="extracted",
            )
            s.add(b)
            await s.flush()
            bidder_ids.append(b.id)
            doc = BidDocument(
                bidder_id=b.id,
                file_name=f"b{i}.docx",
                file_type="docx",
                file_role="technical",
                file_path=f"/tmp/b{i}.docx",
                file_size=1024,
                md5=f"doc_{b.id}" + "0" * 25,
                source_archive=f"b{i}.zip",
            )
            s.add(doc)
            await s.flush()
            for j, (md5, phash, w, h) in enumerate(imgs):
                img = DocumentImage(
                    bid_document_id=doc.id,
                    file_path=f"/tmp/img{i}_{j}.png",
                    md5=md5,
                    phash=phash,
                    width=w,
                    height=h,
                    position="body",
                )
                s.add(img)
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
    )


async def test_s1_md5_and_phash_hits(seeded_reviewer, monkeypatch):
    monkeypatch.delenv("IMAGE_REUSE_ENABLED", raising=False)

    shared_md5 = "a" * 32
    pid, bidders = await _seed(
        seeded_reviewer,
        [
            # bidder 0: 1 张将与 b1 md5 相同,1 张将与 b2 phash 相近
            [(shared_md5, _hex("ffff"), 200, 200),
             ("b0_other" + "0" * 24, _hex("ff00"), 200, 200)],
            # bidder 1: md5 相同
            [(shared_md5, _hex("0000"), 200, 200)],
            # bidder 2: phash 距离 1 ≤ 5
            [("b2_unique" + "0" * 23, _hex("fffe"), 200, 200)],
        ],
    )
    async with async_session() as s:
        ctx = await _ctx(pid, bidders, s)
        pf = await ir_mod.preflight(ctx)
        assert pf.status == "ok"
        result = await ir_mod.run(ctx)
        await s.commit()

        ev = result.evidence_json
        assert ev["enabled"] is True
        assert ev["algorithm_version"] == "image_reuse_v1"
        assert len(ev["md5_matches"]) >= 1
        assert len(ev["phash_matches"]) >= 1
        assert result.score > 0
        # 占位字段
        assert ev["llm_non_generic_judgment"] is None

        # OverallAnalysis 落 1 行
        oas = (
            await s.execute(
                select(OverallAnalysis).where(
                    OverallAnalysis.project_id == pid,
                    OverallAnalysis.dimension == "image_reuse",
                )
            )
        ).scalars().all()
        assert len(oas) == 1


async def test_s2_all_small_images_skip(seeded_reviewer, monkeypatch):
    monkeypatch.delenv("IMAGE_REUSE_ENABLED", raising=False)

    # 全部 16x16 被 min_width/height=32 过滤
    pid, bidders = await _seed(
        seeded_reviewer,
        [
            [("a" * 32, _hex("ff"), 16, 16)],
            [("b" * 32, _hex("ff"), 16, 16)],
        ],
    )
    async with async_session() as s:
        ctx = await _ctx(pid, bidders, s)
        result = await ir_mod.run(ctx)
        await s.commit()

        ev = result.evidence_json
        assert result.score == 0.0
        assert (
            ev.get("skip_reason")
            == "no_comparable_images_after_size_filter"
        )
