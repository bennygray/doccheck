"""L2 - structure_similarity Agent 真实检测链路 (C9)

覆盖 execution-plan §3 C9 的 4 scenario:
1. 目录完全一致命中 → score ≥ 60 + evidence.dimensions.directory.score ≥ 0.9
2. 报价表填充结构一致命中 → score ≥ 60 + evidence.dimensions.field_structure.score ≥ 0.8
3. 独立结构不误报 → score < 30
4. 结构提取失败标"结构缺失" → preflight skip(仅图片,无 docx/xlsx)

策略同 C7/C8:手工构造 ctx 直调 Agent.run()/preflight。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_image import DocumentImage
from app.models.document_sheet import DocumentSheet
from app.models.document_text import DocumentText
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.models.user import User
from app.services.detect.agents import structure_similarity as ss_mod
from app.services.detect.context import AgentContext

pytestmark = pytest.mark.asyncio


# ---------- seed helpers ----------


async def _seed_project(owner_id: int) -> int:
    async with async_session() as s:
        p = Project(name="c9-test", status="ready", owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p.id


async def _seed_bidder(
    project_id: int, name: str, i: int
) -> int:
    async with async_session() as s:
        b = Bidder(
            name=name, project_id=project_id, parse_status="identified"
        )
        s.add(b)
        await s.commit()
        await s.refresh(b)
        return b.id


async def _add_docx_with_paras(
    bidder_id: int, paragraphs: list[str], role: str = "technical", suffix: str = ""
) -> int:
    async with async_session() as s:
        doc = BidDocument(
            bidder_id=bidder_id,
            file_name=f"tech{suffix}.docx",
            file_path=f"/tmp/docx{bidder_id}{suffix}",
            file_size=1000,
            file_type=".docx",
            md5=(f"c9dx{bidder_id}{suffix}" + "y" * 30)[:32],
            file_role=role,
            parse_status="identified",
            source_archive="a.zip",
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
                )
            )
        await s.commit()
        return doc.id


async def _add_xlsx_with_sheets(
    bidder_id: int,
    sheets: list[tuple[str, list[list], list[str]]],
    role: str = "pricing",
    suffix: str = "",
) -> int:
    """sheets = [(sheet_name, rows, merged_cells), ...]"""
    async with async_session() as s:
        doc = BidDocument(
            bidder_id=bidder_id,
            file_name=f"price{suffix}.xlsx",
            file_path=f"/tmp/xlsx{bidder_id}{suffix}",
            file_size=1000,
            file_type=".xlsx",
            md5=(f"c9xl{bidder_id}{suffix}" + "z" * 30)[:32],
            file_role=role,
            parse_status="identified",
            source_archive="a.zip",
        )
        s.add(doc)
        await s.flush()
        for i, (sname, rows, merged) in enumerate(sheets):
            s.add(
                DocumentSheet(
                    bid_document_id=doc.id,
                    sheet_index=i,
                    sheet_name=sname,
                    hidden=False,
                    rows_json=rows,
                    merged_cells_json=merged,
                )
            )
        await s.commit()
        return doc.id


async def _add_image(
    bidder_id: int, role: str = "qualification", suffix: str = ""
) -> int:
    """仅图片 BidDocument + DocumentImage 行(用于 Scenario 4)。"""
    async with async_session() as s:
        doc = BidDocument(
            bidder_id=bidder_id,
            file_name=f"scan{suffix}.jpg",
            file_path=f"/tmp/img{bidder_id}{suffix}",
            file_size=5000,
            file_type=".jpg",
            md5=(f"c9im{bidder_id}{suffix}" + "k" * 30)[:32],
            file_role=role,
            parse_status="identified",
            source_archive="a.zip",
        )
        s.add(doc)
        await s.flush()
        s.add(
            DocumentImage(
                bid_document_id=doc.id,
                file_path=f"/tmp/img{bidder_id}{suffix}.jpg",
                md5=(f"img{bidder_id}" + "m" * 29)[:32],
                phash="f" * 16,
            )
        )
        await s.commit()
        return doc.id


async def _run_structure(
    project_id: int, a_id: int, b_id: int
) -> None:
    async with async_session() as s:
        a = await s.get(Bidder, a_id)
        b = await s.get(Bidder, b_id)
        task = AgentTask(
            project_id=project_id,
            version=1,
            agent_name="structure_similarity",
            agent_type="pair",
            pair_bidder_a_id=a.id,
            pair_bidder_b_id=b.id,
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
            llm_provider=None,
            session=s,
        )
        await ss_mod.run(ctx)
        await s.commit()


async def _run_preflight(
    project_id: int, a_id: int, b_id: int
):
    async with async_session() as s:
        a = await s.get(Bidder, a_id)
        b = await s.get(Bidder, b_id)
        task = AgentTask(
            project_id=project_id,
            version=1,
            agent_name="structure_similarity",
            agent_type="pair",
            pair_bidder_a_id=a.id,
            pair_bidder_b_id=b.id,
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
            llm_provider=None,
            session=s,
        )
        return await ss_mod.preflight(ctx)


async def _load_pc(project_id: int, a_id: int, b_id: int):
    async with async_session() as s:
        stmt = select(PairComparison).where(
            PairComparison.project_id == project_id,
            PairComparison.bidder_a_id == a_id,
            PairComparison.bidder_b_id == b_id,
            PairComparison.dimension == "structure_similarity",
        )
        return (await s.execute(stmt)).scalar_one_or_none()


# ---------- docx chapters helper ----------


def _mk_chapter(num: str, title: str, body: str = "x" * 120) -> list[str]:
    return [f"{num} {title}", body]


def _standard_4_chapter_doc(
    *names: str,
) -> list[str]:
    """返 [标题, body, 标题, body, ...] 4 个章节。"""
    labels = ["第一章", "第二章", "第三章", "第四章"]
    out: list[str] = []
    for i, n in enumerate(names):
        out.extend(_mk_chapter(labels[i], n))
    return out


# ---------- Scenario 1: 目录完全一致命中 ----------

async def test_directory_identical_hit(clean_users, seeded_reviewer: User):
    pid = await _seed_project(seeded_reviewer.id)
    b1 = await _seed_bidder(pid, "B1", 0)
    b2 = await _seed_bidder(pid, "B2", 1)
    # 两侧 docx 章节序列完全相同(归一化后相同)
    paras = _standard_4_chapter_doc("投标函", "技术方案", "商务", "报价")
    await _add_docx_with_paras(b1, paras, suffix="1")
    await _add_docx_with_paras(b2, paras, suffix="2")

    await _run_structure(pid, b1, b2)
    pc = await _load_pc(pid, b1, b2)
    assert pc is not None
    assert pc.evidence_json["algorithm"] == "structure_sim_v1"
    dim_dir = pc.evidence_json["dimensions"]["directory"]
    assert dim_dir["score"] >= 0.9
    assert dim_dir["lcs_length"] == 4
    # 只有目录维度参与(没有 xlsx)
    assert "directory" in pc.evidence_json["participating_dimensions"]
    # score ≥ 60(仅目录参与时 = 0.9 * 100 = 90+)
    assert float(pc.score) >= 60.0


# ---------- Scenario 2: 报价表填充结构一致命中 ----------

async def test_pricing_field_structure_hit(clean_users, seeded_reviewer: User):
    pid = await _seed_project(seeded_reviewer.id)
    b1 = await _seed_bidder(pid, "B1", 0)
    b2 = await _seed_bidder(pid, "B2", 1)
    # 两侧 xlsx 同结构:列头相同、bitmask 相同、合并单元格相同
    rows = [
        ["项目", "数量", "单价"],
        ["泵", 10, 500],
        ["管", 20, 12],
        ["阀", 5, 80],
    ]
    merged = ["A1:C1"]
    await _add_xlsx_with_sheets(
        b1, [("报价汇总", rows, merged)], suffix="1"
    )
    await _add_xlsx_with_sheets(
        b2, [("报价汇总", [r[:] for r in rows], list(merged))], suffix="2"
    )

    await _run_structure(pid, b1, b2)
    pc = await _load_pc(pid, b1, b2)
    assert pc is not None
    dim_field = pc.evidence_json["dimensions"]["field_structure"]
    assert dim_field["score"] >= 0.8
    assert len(dim_field["per_sheet"]) == 1
    assert dim_field["per_sheet"][0]["sub_score"] >= 0.9
    # field + fill 参与(无 docx),目录应 None
    assert pc.evidence_json["dimensions"]["directory"]["score"] is None
    assert set(pc.evidence_json["participating_dimensions"]) == {
        "field_structure",
        "fill_pattern",
    }
    assert float(pc.score) >= 60.0


# ---------- Scenario 3: 独立结构不误报 ----------

async def test_independent_structure_no_false_positive(
    clean_users, seeded_reviewer: User
):
    pid = await _seed_project(seeded_reviewer.id)
    b1 = await _seed_bidder(pid, "B1", 0)
    b2 = await _seed_bidder(pid, "B2", 1)
    # docx 章节完全不同
    paras_a = _standard_4_chapter_doc("投标函", "技术方案", "商务", "报价")
    paras_b = _standard_4_chapter_doc("投标函", "资质证明", "施工组织", "合同条款")
    await _add_docx_with_paras(b1, paras_a, suffix="1")
    await _add_docx_with_paras(b2, paras_b, suffix="2")
    # xlsx 列头 bitmask 都不同
    await _add_xlsx_with_sheets(
        b1,
        [
            (
                "报价",
                [["项目", "数量", "单价"], ["泵", 10, 500], ["管", 20, 12]],
                [],
            )
        ],
        suffix="1",
    )
    await _add_xlsx_with_sheets(
        b2,
        [
            (
                "报价",
                [
                    ["完全", "不同", "的", "表头"],
                    ["a", None, "b", "c"],
                    ["d", "e", None, "f"],
                ],
                ["A1:D1", "A3:B3"],
            )
        ],
        suffix="2",
    )

    await _run_structure(pid, b1, b2)
    pc = await _load_pc(pid, b1, b2)
    assert pc is not None
    assert float(pc.score) < 30.0
    assert pc.is_ironclad is False


# ---------- Scenario 4: 结构提取失败 preflight skip ----------

async def test_structure_missing_preflight_skip(
    clean_users, seeded_reviewer: User
):
    """双方共享角色下仅图片,无 docx/xlsx → preflight skip '结构缺失'。"""
    pid = await _seed_project(seeded_reviewer.id)
    b1 = await _seed_bidder(pid, "B1", 0)
    b2 = await _seed_bidder(pid, "B2", 1)
    # 两侧都只有共享角色 qualification 的图片,无 docx/xlsx
    await _add_image(b1, role="qualification", suffix="1")
    await _add_image(b2, role="qualification", suffix="2")

    r = await _run_preflight(pid, b1, b2)
    assert r.status == "skip"
    assert r.reason == "结构缺失"
    # preflight skip,run 不应被调用,所以不应有 PairComparison
    pc = await _load_pc(pid, b1, b2)
    assert pc is None
