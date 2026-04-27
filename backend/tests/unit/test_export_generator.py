"""L1 - C15 export generator 纯函数 + templates + cleanup

覆盖:
- build_render_context 装配结构(project/report/dimensions/top_pairs/review)
- 维度顺序 = DIMENSION_WEIGHTS
- top_pairs 铁证优先 + 按 score 降序
- review 段:未复核 → None;已复核 → dict
- render_to_file 产出可读 docx(含占位符被替换)
- templates.load_template None → builtin;无效 id → TemplateLoadError
- cleanup._seconds_until_next_0200 基本语义
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.detect.judge import DIMENSION_WEIGHTS
from app.services.export.cleanup import _seconds_until_next_0200
from app.services.export.generator import (
    build_render_context,
    render_to_file,
)
from app.services.export.templates import (
    TemplateLoadError,
    builtin_template_path,
    load_template,
)


def _mock_ar(**overrides):
    base = dict(
        id=1,
        project_id=10,
        version=1,
        total_score=Decimal("75.5"),
        risk_level="medium",
        llm_conclusion="some judgment",
        manual_review_status=None,
        manual_review_comment=None,
        reviewer_id=None,
        reviewed_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _mock_project():
    return SimpleNamespace(
        id=10,
        name="Project-X",
        created_at=datetime(2026, 4, 16, tzinfo=timezone.utc),
    )


def _mock_oa(dim, score, *, iron=False, review=None):
    ev = {"summary": f"{dim}-summary"}
    if iron:
        ev["has_iron_evidence"] = True
    return SimpleNamespace(
        dimension=dim,
        score=Decimal(str(score)),
        evidence_json=ev,
        manual_review_json=review,
    )


def _mock_pc(dim, score, *, iron=False):
    return SimpleNamespace(
        dimension=dim,
        bidder_a_id=1,
        bidder_b_id=2,
        score=Decimal(str(score)),
        is_ironclad=iron,
        evidence_json={"summary": f"pc-{dim}-{score}"},
    )


# ============================================================ build_render_context


def test_context_basic_structure():
    ar = _mock_ar()
    ctx = build_render_context(
        project=_mock_project(),
        ar=ar,
        oa_rows=[],
        pc_rows=[],
    )
    assert ctx["project"]["name"] == "Project-X"
    assert ctx["report"]["total_score"] == 75.5
    assert ctx["report"]["risk_level"] == "medium"
    assert ctx["review"] is None
    # 13 维度全覆盖,顺序匹配(fix-bug-triple-and-direction-high +2 新维度)
    assert [d["name"] for d in ctx["dimensions"]] == list(DIMENSION_WEIGHTS.keys())
    assert all(d["best_score"] == 0.0 for d in ctx["dimensions"])


def test_context_best_score_prefers_higher_oa_vs_pc():
    ctx = build_render_context(
        project=_mock_project(),
        ar=_mock_ar(),
        oa_rows=[_mock_oa("text_similarity", 60)],
        pc_rows=[_mock_pc("text_similarity", 80)],
    )
    dims = {d["name"]: d for d in ctx["dimensions"]}
    # PC 80 更高
    assert dims["text_similarity"]["best_score"] == 80.0


def test_context_ironclad_from_either_source():
    ctx = build_render_context(
        project=_mock_project(),
        ar=_mock_ar(),
        oa_rows=[_mock_oa("metadata_author", 50, iron=True)],
        pc_rows=[_mock_pc("style", 60, iron=True)],
    )
    dims = {d["name"]: d for d in ctx["dimensions"]}
    assert dims["metadata_author"]["is_ironclad"] is True
    assert dims["style"]["is_ironclad"] is True


def test_context_top_pairs_ironclad_first_then_score_desc():
    pcs = [
        _mock_pc("d1", 50, iron=False),
        _mock_pc("d2", 95, iron=False),
        _mock_pc("d3", 40, iron=True),
        _mock_pc("d4", 30, iron=False),
    ]
    ctx = build_render_context(
        project=_mock_project(),
        ar=_mock_ar(),
        oa_rows=[],
        pc_rows=pcs,
        top_k=3,
    )
    tops = ctx["top_pairs"]
    assert len(tops) == 3
    # 铁证优先
    assert tops[0]["is_ironclad"] is True
    assert tops[0]["dimension"] == "d3"
    # 铁证之后按分数降序
    assert tops[1]["dimension"] == "d2"
    assert tops[2]["dimension"] == "d1"


def test_context_review_fields():
    ar = _mock_ar(
        manual_review_status="confirmed",
        manual_review_comment="ok",
        reviewer_id=7,
        reviewed_at=datetime(2026, 4, 16, 10, 0, tzinfo=timezone.utc),
    )
    ctx = build_render_context(
        project=_mock_project(), ar=ar, oa_rows=[], pc_rows=[]
    )
    assert ctx["review"] is not None
    assert ctx["review"]["status"] == "confirmed"
    assert ctx["review"]["comment"] == "ok"
    assert ctx["review"]["reviewer_id"] == 7
    assert "2026-04-16" in ctx["review"]["reviewed_at"]


# ============================================================ render_to_file


def test_render_to_file_produces_readable_docx(tmp_path):
    ctx = {
        "project": {"name": "ProjX", "submitted_at": "2026-04-16"},
        "report": {
            "version": 1,
            "total_score": 75.5,
            "risk_level": "medium",
            "llm_conclusion": "some text",
        },
        "dimensions": [
            {
                "name": "text_similarity",
                "best_score": 80.0,
                "is_ironclad": True,
                "evidence_summary": "文本重合",
            }
        ],
        "top_pairs": [
            {
                "bidder_a": 1,
                "bidder_b": 2,
                "dimension": "meta",
                "score": 90.0,
                "is_ironclad": True,
                "summary": "同一作者",
            }
        ],
        "review": None,
    }
    out = tmp_path / "out.docx"
    size = render_to_file(builtin_template_path(), ctx, out)
    assert size > 0
    assert out.exists()
    # 回读断言占位符被替换
    from docx import Document

    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "ProjX" in text
    assert "75.5" in text
    assert "text_similarity" in text
    # 无 review:确认段不出现复核评论
    assert "ok" not in text


# ============================================================ templates


@pytest.mark.asyncio
async def test_load_template_none_returns_builtin():
    # session 参数可以传 None,因为 None template_id 路径不查 DB
    path = await load_template(None, None)  # type: ignore[arg-type]
    assert path.exists()
    assert path.name == "default.docx"


@pytest.mark.asyncio
async def test_load_template_missing_raises():
    from sqlalchemy.ext.asyncio import AsyncSession

    class _FakeSession(AsyncSession):
        def __init__(self):
            pass

        async def get(self, *args, **kwargs):
            return None

    with pytest.raises(TemplateLoadError):
        await load_template(_FakeSession(), 999999)


# ============================================================ cleanup helper


def test_seconds_until_next_0200_before_2am():
    from datetime import datetime as dt

    now = dt(2026, 4, 16, 1, 30, 0)
    # 应约等于 30 分钟 = 1800 秒
    diff = _seconds_until_next_0200(now)
    assert 1700 <= diff <= 1900


def test_seconds_until_next_0200_after_2am_wraps_to_next_day():
    from datetime import datetime as dt

    now = dt(2026, 4, 16, 14, 0, 0)
    # 应约 12 小时左右
    diff = _seconds_until_next_0200(now)
    assert 11 * 3600 <= diff <= 13 * 3600
