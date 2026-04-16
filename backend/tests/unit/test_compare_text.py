"""L1 — C16 compare/text endpoint 单元测试。

直接测试路由函数的逻辑:
- 正常对比(有 PairComparison + DocumentText)
- 未指定 doc_role 取 score 最高
- 无检测结果 → matches=[] 段落正常返回
- 无文档 → 空段落
- 超限分页
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.compare import TextCompareResponse


def _db_result(scalars_list):
    """模拟 (await session.execute(...)) 返回值:同步 .scalars().all()。"""
    result = MagicMock()
    result.scalars.return_value.all.return_value = scalars_list
    return result


def _db_scalar_one(value):
    """模拟 (await session.execute(select(func.count()))).scalar_one()。"""
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


def _db_scalar_one_or_none(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_pc(bidder_a_id, bidder_b_id, score, doc_role, samples=None):
    class FakePC:
        pass

    pc = FakePC()
    pc.bidder_a_id = bidder_a_id
    pc.bidder_b_id = bidder_b_id
    pc.score = Decimal(str(score))
    pc.dimension = "text_similarity"
    pc.evidence_json = {
        "doc_role": doc_role,
        "doc_id_a": 100,
        "doc_id_b": 200,
        "samples": samples or [],
    }
    return pc


def _make_dt(doc_id, para_idx, text):
    class FakeDT:
        pass

    dt = FakeDT()
    dt.bid_document_id = doc_id
    dt.paragraph_index = para_idx
    dt.text = text
    dt.location = "body"
    return dt


@pytest.mark.asyncio
async def test_text_compare_normal():
    """正常对比:有 PC + 有段落 + 有 matches。"""
    from app.api.routes.compare import compare_text

    samples = [
        {"a_idx": 0, "b_idx": 1, "sim": 0.85, "label": "plagiarism",
         "a_text": "段落A", "b_text": "段落B"},
    ]
    pc = _make_pc(1, 2, 75.0, "commercial", samples)

    left_paras = [_make_dt(100, 0, "段落A"), _make_dt(100, 1, "段落A-2")]
    right_paras = [_make_dt(200, 0, "段落B-0"), _make_dt(200, 1, "段落B")]

    mock_session = AsyncMock()

    with (
        patch("app.api.routes.compare._visible_project", new_callable=AsyncMock),
        patch("app.api.routes.compare._latest_version", new_callable=AsyncMock, return_value=1),
    ):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result([pc]),                  # PC query
            _db_scalar_one(2),                 # left count
            _db_result(left_paras),            # left rows
            _db_scalar_one(2),                 # right count
            _db_result(right_paras),           # right rows
        ])

        user = AsyncMock()
        resp = await compare_text(
            project_id=1, bidder_a=1, bidder_b=2,
            doc_role="commercial", version=1,
            limit=5000, offset=0,
            session=mock_session, user=user,
        )

    assert isinstance(resp, TextCompareResponse)
    assert resp.bidder_a_id == 1
    assert resp.bidder_b_id == 2
    assert resp.doc_role == "commercial"
    assert len(resp.matches) == 1
    assert resp.matches[0].sim == 0.85
    assert resp.matches[0].label == "plagiarism"
    assert len(resp.left_paragraphs) == 2
    assert len(resp.right_paragraphs) == 2


@pytest.mark.asyncio
async def test_text_compare_no_doc_role_takes_highest_score():
    """未指定 doc_role 时取 score 最高的 PC。"""
    from app.api.routes.compare import compare_text

    pc_low = _make_pc(1, 2, 50.0, "technical")
    pc_high = _make_pc(1, 2, 80.0, "commercial",
                       [{"a_idx": 0, "b_idx": 0, "sim": 0.9, "label": None}])

    mock_session = AsyncMock()

    with (
        patch("app.api.routes.compare._visible_project", new_callable=AsyncMock),
        patch("app.api.routes.compare._latest_version", new_callable=AsyncMock, return_value=1),
    ):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result([pc_low, pc_high]),
            _db_scalar_one(0), _db_result([]),   # left
            _db_scalar_one(0), _db_result([]),   # right
        ])

        user = AsyncMock()
        resp = await compare_text(
            project_id=1, bidder_a=1, bidder_b=2,
            doc_role=None, version=1,
            limit=5000, offset=0,
            session=mock_session, user=user,
        )

    assert resp.doc_role == "commercial"
    assert len(resp.matches) == 1
    assert "technical" in resp.available_roles
    assert "commercial" in resp.available_roles


@pytest.mark.asyncio
async def test_text_compare_no_detection_result():
    """无检测结果 → matches=[] 但需要 fallback 查文档。"""
    from app.api.routes.compare import compare_text

    mock_session = AsyncMock()

    with (
        patch("app.api.routes.compare._visible_project", new_callable=AsyncMock),
        patch("app.api.routes.compare._latest_version", new_callable=AsyncMock, return_value=1),
        patch("app.api.routes.compare._find_doc_id", new_callable=AsyncMock, return_value=None),
    ):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result([]),  # no PCs
        ])

        user = AsyncMock()
        resp = await compare_text(
            project_id=1, bidder_a=1, bidder_b=2,
            doc_role="commercial", version=1,
            limit=5000, offset=0,
            session=mock_session, user=user,
        )

    assert resp.matches == []
    assert resp.left_paragraphs == []
    assert resp.right_paragraphs == []


@pytest.mark.asyncio
async def test_text_compare_no_document():
    """一侧无文档 → 该侧段落空。"""
    from app.api.routes.compare import compare_text

    pc = _make_pc(1, 2, 70.0, "commercial")
    pc.evidence_json["doc_id_a"] = 100
    pc.evidence_json["doc_id_b"] = None

    mock_session = AsyncMock()

    with (
        patch("app.api.routes.compare._visible_project", new_callable=AsyncMock),
        patch("app.api.routes.compare._latest_version", new_callable=AsyncMock, return_value=1),
        patch("app.api.routes.compare._find_doc_id", new_callable=AsyncMock, return_value=None),
    ):
        left_dt = _make_dt(100, 0, "左侧段落")
        mock_session.execute = AsyncMock(side_effect=[
            _db_result([pc]),
            _db_scalar_one(1), _db_result([left_dt]),  # left
            # right: doc_id=None → _load_paragraphs returns [],0 directly
        ])

        user = AsyncMock()
        resp = await compare_text(
            project_id=1, bidder_a=1, bidder_b=2,
            doc_role="commercial", version=1,
            limit=5000, offset=0,
            session=mock_session, user=user,
        )

    assert len(resp.left_paragraphs) == 1
    assert resp.right_paragraphs == []


@pytest.mark.asyncio
async def test_text_compare_pagination():
    """段落超限 → has_more=True。"""
    from app.api.routes.compare import compare_text

    pc = _make_pc(1, 2, 70.0, "commercial")

    mock_session = AsyncMock()

    with (
        patch("app.api.routes.compare._visible_project", new_callable=AsyncMock),
        patch("app.api.routes.compare._latest_version", new_callable=AsyncMock, return_value=1),
    ):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result([pc]),
            _db_scalar_one(10),                                     # left count=10
            _db_result([_make_dt(100, i, f"p{i}") for i in range(3)]),  # left 3 rows
            _db_scalar_one(5),                                      # right count=5
            _db_result([_make_dt(200, i, f"q{i}") for i in range(3)]),  # right 3 rows
        ])

        user = AsyncMock()
        resp = await compare_text(
            project_id=1, bidder_a=1, bidder_b=2,
            doc_role="commercial", version=1,
            limit=3, offset=0,
            session=mock_session, user=user,
        )

    assert resp.has_more is True
    assert resp.total_count_left == 10
    assert resp.total_count_right == 5
    assert len(resp.left_paragraphs) == 3
