"""L2 - metadata 3 Agent 真实检测链路 (C10)

覆盖 execution-plan §3 C10 的 5 Scenario:
1. 作者相同命中(metadata_author)
2. 时间聚集命中(metadata_time)
3. 机器指纹碰撞命中(metadata_machine)
4. 元数据被清洗 → 3 Agent preflight 全 skip,不写 PairComparison
5. 子检测 flag 可单独关闭

策略同 C7/C8/C9:手工构造 ctx 直调 Agent.run() / preflight(不走 engine 协程)。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_metadata import DocumentMetadata
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.models.user import User
from app.services.detect.agents import (
    metadata_author as author_mod,
    metadata_machine as machine_mod,
    metadata_time as time_mod,
)
from app.services.detect.context import AgentContext

pytestmark = pytest.mark.asyncio

UTC = timezone.utc


# ---------- seed helpers ----------


async def _seed_project(owner_id: int) -> int:
    async with async_session() as s:
        p = Project(name="c10-test", status="ready", owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p.id


async def _seed_bidder(project_id: int, name: str) -> int:
    async with async_session() as s:
        b = Bidder(
            name=name, project_id=project_id, parse_status="identified"
        )
        s.add(b)
        await s.commit()
        await s.refresh(b)
        return b.id


async def _add_doc_with_meta(
    bidder_id: int,
    *,
    role: str = "technical",
    file_ext: str = ".docx",
    suffix: str = "",
    author: str | None = None,
    last_saved_by: str | None = None,
    company: str | None = None,
    app_name: str | None = None,
    app_version: str | None = None,
    template: str | None = None,
    doc_created_at: datetime | None = None,
    doc_modified_at: datetime | None = None,
) -> int:
    async with async_session() as s:
        doc = BidDocument(
            bidder_id=bidder_id,
            file_name=f"d{suffix}{file_ext}",
            file_path=f"/tmp/c10{bidder_id}{suffix}{file_ext}",
            file_size=100,
            file_type=file_ext,
            md5=(f"c10{bidder_id}{suffix}" + "m" * 30)[:32],
            file_role=role,
            parse_status="identified",
            source_archive="a.zip",
        )
        s.add(doc)
        await s.flush()
        s.add(
            DocumentMetadata(
                bid_document_id=doc.id,
                author=author,
                last_saved_by=last_saved_by,
                company=company,
                doc_created_at=doc_created_at,
                doc_modified_at=doc_modified_at,
                app_name=app_name,
                app_version=app_version,
                template=template,
            )
        )
        await s.commit()
        return doc.id


async def _run_agent(mod, agent_name: str, pid: int, a_id: int, b_id: int):
    async with async_session() as s:
        a = await s.get(Bidder, a_id)
        b = await s.get(Bidder, b_id)
        task = AgentTask(
            project_id=pid,
            version=1,
            agent_name=agent_name,
            agent_type="pair",
            pair_bidder_a_id=a.id,
            pair_bidder_b_id=b.id,
            status="pending",
        )
        s.add(task)
        await s.flush()
        ctx = AgentContext(
            project_id=pid,
            version=1,
            agent_task=task,
            bidder_a=a,
            bidder_b=b,
            all_bidders=[],
            llm_provider=None,
            session=s,
        )
        result = await mod.run(ctx)
        await s.commit()
        return result


async def _run_preflight(mod, pid: int, a_id: int, b_id: int):
    async with async_session() as s:
        a = await s.get(Bidder, a_id)
        b = await s.get(Bidder, b_id)
        task = AgentTask(
            project_id=pid,
            version=1,
            agent_name="metadata_x",
            agent_type="pair",
            pair_bidder_a_id=a.id,
            pair_bidder_b_id=b.id,
            status="pending",
        )
        s.add(task)
        await s.flush()
        ctx = AgentContext(
            project_id=pid,
            version=1,
            agent_task=task,
            bidder_a=a,
            bidder_b=b,
            all_bidders=[],
            llm_provider=None,
            session=s,
        )
        return await mod.preflight(ctx)


async def _load_pc(pid: int, a_id: int, b_id: int, dimension: str):
    async with async_session() as s:
        stmt = select(PairComparison).where(
            PairComparison.project_id == pid,
            PairComparison.bidder_a_id == a_id,
            PairComparison.bidder_b_id == b_id,
            PairComparison.dimension == dimension,
        )
        return (await s.execute(stmt)).scalar_one_or_none()


# ---------- Scenario 1: author 相同命中 ----------


async def test_scenario_author_collision(clean_users, seeded_reviewer: User):
    pid = await _seed_project(seeded_reviewer.id)
    a = await _seed_bidder(pid, "A")
    b = await _seed_bidder(pid, "B")
    await _add_doc_with_meta(a, author="张三", suffix="a1")
    await _add_doc_with_meta(b, author="张三", suffix="b1")

    result = await _run_agent(
        author_mod, "metadata_author", pid, a, b
    )
    assert result.evidence_json["algorithm"] == "metadata_author_v1"
    # author 单字段命中 1.0;另两字段单侧空 → 不进 sub_scores 重归一 → score = 100
    assert result.score > 0
    assert "author" in result.evidence_json["participating_fields"]
    pc = await _load_pc(pid, a, b, "metadata_author")
    assert pc is not None
    assert float(pc.score) > 0


# ---------- Scenario 2: 5 分钟内时间聚集命中 ----------


async def test_scenario_time_cluster(clean_users, seeded_reviewer: User):
    pid = await _seed_project(seeded_reviewer.id)
    a = await _seed_bidder(pid, "A")
    b = await _seed_bidder(pid, "B")
    base = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    await _add_doc_with_meta(a, doc_modified_at=base, suffix="a1")
    await _add_doc_with_meta(
        a, doc_modified_at=base + timedelta(minutes=2), suffix="a2"
    )
    await _add_doc_with_meta(
        b, doc_modified_at=base + timedelta(minutes=1), suffix="b1"
    )
    await _add_doc_with_meta(
        b, doc_modified_at=base + timedelta(minutes=3), suffix="b2"
    )

    result = await _run_agent(time_mod, "metadata_time", pid, a, b)
    assert result.evidence_json["algorithm"] == "metadata_time_v1"
    assert result.score > 0
    assert result.evidence_json["sub_scores"].get("modified_at_cluster", 0) > 0
    pc = await _load_pc(pid, a, b, "metadata_time")
    assert pc is not None


# ---------- Scenario 3: 机器指纹三元组碰撞 ----------


async def test_scenario_machine_fingerprint(
    clean_users, seeded_reviewer: User
):
    pid = await _seed_project(seeded_reviewer.id)
    a = await _seed_bidder(pid, "A")
    b = await _seed_bidder(pid, "B")
    kwargs = dict(
        app_name="Microsoft Office Word",
        app_version="16.0000",
        template="Normal.dotm",
    )
    await _add_doc_with_meta(a, **kwargs, suffix="a1")
    await _add_doc_with_meta(a, **kwargs, suffix="a2")
    await _add_doc_with_meta(b, **kwargs, suffix="b1")

    result = await _run_agent(machine_mod, "metadata_machine", pid, a, b)
    assert result.evidence_json["algorithm"] == "metadata_machine_v1"
    # 3 doc 全部覆盖元组 → score=100,is_ironclad=True(≥85)
    assert result.score >= 85.0
    pc = await _load_pc(pid, a, b, "metadata_machine")
    assert pc is not None
    assert pc.is_ironclad is True


# ---------- Scenario 4: 元数据被清洗 → 3 Agent preflight 全 skip ----------


async def test_scenario_metadata_cleared_preflight_skip(
    clean_users, seeded_reviewer: User
):
    """两 bidder 的 BidDocument 的 DocumentMetadata 所有字段全 None。"""
    pid = await _seed_project(seeded_reviewer.id)
    a = await _seed_bidder(pid, "A")
    b = await _seed_bidder(pid, "B")
    # 所有字段 None(被清洗状态)
    await _add_doc_with_meta(a, suffix="a1")
    await _add_doc_with_meta(b, suffix="b1")

    for mod, dim in [
        (author_mod, "metadata_author"),
        (time_mod, "metadata_time"),
        (machine_mod, "metadata_machine"),
    ]:
        r = await _run_preflight(mod, pid, a, b)
        assert r.status == "skip"
        # preflight skip → 不写 PairComparison
        pc = await _load_pc(pid, a, b, dim)
        assert pc is None


# ---------- Scenario 5: 子检测 flag 单独关闭 ----------


async def test_scenario_flag_disable_single_agent(
    clean_users, seeded_reviewer: User, monkeypatch
):
    """METADATA_AUTHOR_ENABLED=false:metadata_author 返 enabled=false,但其他 2 仍正常。"""
    pid = await _seed_project(seeded_reviewer.id)
    a = await _seed_bidder(pid, "A")
    b = await _seed_bidder(pid, "B")
    # 作者相同 + 时间相近 + 机器指纹一致(全部强信号)
    base = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    common_kwargs = dict(
        author="张三",
        doc_modified_at=base,
        app_name="Word",
        app_version="16.0",
        template="Normal.dotm",
    )
    await _add_doc_with_meta(a, **common_kwargs, suffix="a1")
    await _add_doc_with_meta(
        b,
        **(common_kwargs | {"doc_modified_at": base + timedelta(minutes=1)}),
        suffix="b1",
    )

    monkeypatch.setenv("METADATA_AUTHOR_ENABLED", "false")
    r_author = await _run_agent(author_mod, "metadata_author", pid, a, b)
    assert r_author.evidence_json["enabled"] is False
    assert r_author.score == 0.0

    # 其他 2 Agent 不受影响
    r_time = await _run_agent(time_mod, "metadata_time", pid, a, b)
    assert r_time.evidence_json["enabled"] is True
    assert r_time.score > 0
    r_machine = await _run_agent(machine_mod, "metadata_machine", pid, a, b)
    assert r_machine.evidence_json["enabled"] is True
    assert r_machine.score > 0
