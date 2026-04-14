"""L1 - structure_similarity Agent 主流程 (C9)

Mock loaders 驱动 3 维度组合,验证:
- preflight 3 路径(无共享角色 / 有但无 docx/xlsx / 有)
- run 三维度全参与
- run xlsx-only
- run docx-only
- run 全 skip(3 维度全 None)
- evidence schema 字段齐
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.detect.agents import structure_similarity as ss_mod
from app.services.detect.agents.structure_sim_impl import loaders
from app.services.detect.agents.structure_sim_impl.field_sig import SheetInput
from app.services.detect.agents.structure_sim_impl.loaders import (
    DocxPair,
    XlsxPair,
)
from app.services.detect.context import AgentContext


def _bidder(id: int, name: str):
    return SimpleNamespace(id=id, name=name)


def _make_ctx():
    session = AsyncMock()
    session.add = lambda *a, **kw: None
    session.flush = AsyncMock()
    return AgentContext(
        project_id=1,
        version=1,
        agent_task=SimpleNamespace(),
        bidder_a=_bidder(10, "甲"),
        bidder_b=_bidder(20, "乙"),
        all_bidders=[],
        llm_provider=None,
        session=session,
    )


def _titles(*names: str) -> list[str]:
    return [f"第{i + 1}章 {n}" for i, n in enumerate(names)]


def _sheet(name: str, rows: list[list], merged: list[str] | None = None):
    return SheetInput(name, rows, merged or [])


@pytest.mark.asyncio
async def test_preflight_no_shared_role(monkeypatch):
    async def _share_any(*a, **k):
        return False

    monkeypatch.setattr(ss_mod, "bidders_share_any_role", _share_any)
    ctx = _make_ctx()
    r = await ss_mod.preflight(ctx)
    assert r.status == "skip"
    assert r.reason == "缺少可对比文档"


@pytest.mark.asyncio
async def test_preflight_no_docx_no_xlsx(monkeypatch):
    async def _share_any(*a, **k):
        return True

    async def _share_ext(*a, **k):
        return False

    monkeypatch.setattr(ss_mod, "bidders_share_any_role", _share_any)
    monkeypatch.setattr(ss_mod, "bidders_share_role_with_ext", _share_ext)
    ctx = _make_ctx()
    r = await ss_mod.preflight(ctx)
    assert r.status == "skip"
    assert r.reason == "结构缺失"


@pytest.mark.asyncio
async def test_preflight_ok(monkeypatch):
    async def _share_any(*a, **k):
        return True

    call_log = []

    async def _share_ext(session, a, b, exts):
        call_log.append(exts)
        # 第 1 次问 .docx 返 True,第 2 次 .xlsx 返 False
        return ".docx" in exts

    monkeypatch.setattr(ss_mod, "bidders_share_any_role", _share_any)
    monkeypatch.setattr(ss_mod, "bidders_share_role_with_ext", _share_ext)
    ctx = _make_ctx()
    r = await ss_mod.preflight(ctx)
    assert r.status == "ok"


@pytest.mark.asyncio
async def test_run_three_dims_all_participate(monkeypatch):
    """docx+xlsx 都有,三维度全进。"""
    docx = DocxPair(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        titles_a=_titles("投标函", "技术方案", "商务", "报价"),
        titles_b=_titles("投标函", "技术方案", "商务", "报价"),
    )
    rows = [["h1", "h2"], ["a", 1], ["b", 2]]
    xlsx = XlsxPair(
        doc_role="pricing",
        doc_id_a=3,
        doc_id_b=4,
        sheets_a=[_sheet("S", rows, ["A1:B1"])],
        sheets_b=[_sheet("S", [r[:] for r in rows], ["A1:B1"])],
    )

    async def _load_docx(*a, **k):
        return docx

    async def _load_xlsx(*a, **k):
        return xlsx

    monkeypatch.setattr(loaders, "load_docx_titles_pair", _load_docx)
    monkeypatch.setattr(loaders, "load_xlsx_sheets_pair", _load_xlsx)

    ctx = _make_ctx()
    r = await ss_mod.run(ctx)
    assert r.score == 100.0  # 三维度全 1.0
    ev = r.evidence_json
    assert ev["algorithm"] == "structure_sim_v1"
    assert set(ev["participating_dimensions"]) == {
        "directory",
        "field_structure",
        "fill_pattern",
    }
    assert ev["dimensions"]["directory"]["score"] == 1.0
    assert ev["dimensions"]["directory"]["lcs_length"] == 4
    assert ev["dimensions"]["field_structure"]["score"] == 1.0
    assert ev["dimensions"]["fill_pattern"]["score"] == 1.0
    assert ev["doc_role"] == "pricing+technical"  # merged
    assert ev["doc_id_a"] == [1, 3]
    assert ev["doc_id_b"] == [2, 4]


@pytest.mark.asyncio
async def test_run_xlsx_only(monkeypatch):
    rows = [["h1", "h2"], ["a", 1], ["b", 2]]
    xlsx = XlsxPair(
        doc_role="pricing",
        doc_id_a=3,
        doc_id_b=4,
        sheets_a=[_sheet("S", rows, [])],
        sheets_b=[_sheet("S", [r[:] for r in rows], [])],
    )

    async def _load_docx(*a, **k):
        return None  # 无共享 docx

    async def _load_xlsx(*a, **k):
        return xlsx

    monkeypatch.setattr(loaders, "load_docx_titles_pair", _load_docx)
    monkeypatch.setattr(loaders, "load_xlsx_sheets_pair", _load_xlsx)

    ctx = _make_ctx()
    r = await ss_mod.run(ctx)
    ev = r.evidence_json
    assert "directory" not in ev["participating_dimensions"]
    assert set(ev["participating_dimensions"]) == {
        "field_structure",
        "fill_pattern",
    }
    # (1.0 * 0.3 + 1.0 * 0.3) / 0.6 = 1.0 → 100
    assert r.score == 100.0
    assert ev["dimensions"]["directory"]["score"] is None
    assert ev["dimensions"]["directory"]["reason"] == "docx_shared_role_missing"


@pytest.mark.asyncio
async def test_run_docx_only(monkeypatch):
    docx = DocxPair(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        titles_a=_titles("投标函", "技术", "商务"),
        titles_b=_titles("投标函", "技术", "商务"),
    )

    async def _load_docx(*a, **k):
        return docx

    async def _load_xlsx(*a, **k):
        return None  # 无共享 xlsx

    monkeypatch.setattr(loaders, "load_docx_titles_pair", _load_docx)
    monkeypatch.setattr(loaders, "load_xlsx_sheets_pair", _load_xlsx)

    ctx = _make_ctx()
    r = await ss_mod.run(ctx)
    ev = r.evidence_json
    assert ev["participating_dimensions"] == ["directory"]
    # dir=1.0 → 1.0 / 1.0 * 100 = 100
    assert r.score == 100.0
    assert ev["dimensions"]["field_structure"]["score"] is None
    assert ev["dimensions"]["field_structure"]["reason"] == "xlsx_sheet_missing"


@pytest.mark.asyncio
async def test_run_all_skipped_when_extraction_fails(monkeypatch):
    """docx 章节数不足 + xlsx 无 DocumentSheet → 3 维度全 None → score=0 哨兵。"""

    # docx 章节数不足(只有 1 章)
    docx = DocxPair(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        titles_a=["第1章 投标函"],
        titles_b=["第1章 投标函"],
    )

    async def _load_docx(*a, **k):
        return docx

    async def _load_xlsx(*a, **k):
        return None  # 无 xlsx

    monkeypatch.setattr(loaders, "load_docx_titles_pair", _load_docx)
    monkeypatch.setattr(loaders, "load_xlsx_sheets_pair", _load_xlsx)

    ctx = _make_ctx()
    r = await ss_mod.run(ctx)
    assert r.score == 0.0
    assert r.summary.startswith("结构缺失")
    ev = r.evidence_json
    assert ev["participating_dimensions"] == []
    assert ev["weights_used"] == {}
    assert ev["dimensions"]["directory"]["score"] is None
    assert ev["dimensions"]["directory"]["reason"] == "chapters_below_min"
    assert ev["dimensions"]["field_structure"]["score"] is None
    assert ev["dimensions"]["field_structure"]["reason"] == "xlsx_sheet_missing"


@pytest.mark.asyncio
async def test_run_ironclad_triggered(monkeypatch):
    """任一维度 ≥ 0.9 且 total ≥ 85 → is_ironclad。"""
    docx = DocxPair(
        doc_role="technical",
        doc_id_a=1,
        doc_id_b=2,
        titles_a=_titles("A", "B", "C", "D", "E"),
        titles_b=_titles("A", "B", "C", "D", "E"),
    )

    async def _load_docx(*a, **k):
        return docx

    async def _load_xlsx(*a, **k):
        return None

    monkeypatch.setattr(loaders, "load_docx_titles_pair", _load_docx)
    monkeypatch.setattr(loaders, "load_xlsx_sheets_pair", _load_xlsx)

    ctx = _make_ctx()
    r = await ss_mod.run(ctx)
    assert r.score == 100.0
    assert "铁证" in r.summary
