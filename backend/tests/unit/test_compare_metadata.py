"""L1 — C16 compare/metadata endpoint 单元测试。

- 正常元数据矩阵
- 通用值标记(METADATA_COMMON_VALUES)
- 高频值标记(≥80%)
- 无元数据投标人
- 空项目
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.compare import MetaCompareResponse


def _db_result(scalars_list):
    result = MagicMock()
    result.scalars.return_value.all.return_value = scalars_list
    return result


def _make_bidder(bid_id, name, project_id=1):
    class FB:
        pass

    b = FB()
    b.id = bid_id
    b.name = name
    b.project_id = project_id
    b.deleted_at = None
    return b


def _make_doc(doc_id, bidder_id, file_role):
    class FD:
        pass

    d = FD()
    d.id = doc_id
    d.bidder_id = bidder_id
    d.file_role = file_role
    return d


def _make_meta(doc_id, **kwargs):
    class FM:
        pass

    m = FM()
    m.bid_document_id = doc_id
    m.author = kwargs.get("author")
    m.last_saved_by = kwargs.get("last_saved_by")
    m.company = kwargs.get("company")
    m.app_name = kwargs.get("app_name")
    m.app_version = kwargs.get("app_version")
    m.template = kwargs.get("template")
    m.doc_created_at = kwargs.get("doc_created_at")
    m.doc_modified_at = kwargs.get("doc_modified_at")
    return m


@pytest.mark.asyncio
async def test_metadata_compare_normal():
    """3 bidder,正常矩阵,相同值同 color_group。"""
    from app.api.routes.compare import compare_metadata

    bidders = [_make_bidder(1, "A"), _make_bidder(2, "B"), _make_bidder(3, "C")]
    docs = [
        _make_doc(10, 1, "commercial"),
        _make_doc(20, 2, "commercial"),
        _make_doc(30, 3, "technical"),
    ]
    metas = [
        _make_meta(10, author="张三", app_name="WPS Office"),
        _make_meta(20, author="张三", app_name="Microsoft Word"),
        _make_meta(30, author="李四", app_name="WPS Office"),
    ]

    mock_session = AsyncMock()

    with patch("app.api.routes.compare._visible_project", new_callable=AsyncMock):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result(bidders),
            _db_result(docs),
            _db_result(metas),
        ])

        user = AsyncMock()
        resp = await compare_metadata(
            project_id=1, version=None,
            session=mock_session, user=user,
        )

    assert isinstance(resp, MetaCompareResponse)
    assert len(resp.bidders) == 3
    assert len(resp.fields) == 8

    author_row = [f for f in resp.fields if f.field_name == "author"][0]
    assert author_row.values[0].value == "张三"
    assert author_row.values[1].value == "张三"
    assert author_row.values[2].value == "李四"
    assert author_row.values[0].color_group == author_row.values[1].color_group
    assert author_row.values[2].color_group != author_row.values[0].color_group


@pytest.mark.asyncio
async def test_metadata_common_value_marked():
    """author='Administrator' → is_common=True。"""
    from app.api.routes.compare import compare_metadata

    bidders = [_make_bidder(1, "A")]
    docs = [_make_doc(10, 1, "commercial")]
    metas = [_make_meta(10, author="Administrator", app_name="Word")]

    mock_session = AsyncMock()

    with patch("app.api.routes.compare._visible_project", new_callable=AsyncMock):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result(bidders),
            _db_result(docs),
            _db_result(metas),
        ])

        user = AsyncMock()
        resp = await compare_metadata(
            project_id=1, version=None,
            session=mock_session, user=user,
        )

    author_row = [f for f in resp.fields if f.field_name == "author"][0]
    assert author_row.values[0].is_common is True


@pytest.mark.asyncio
async def test_metadata_high_frequency_marked():
    """5 个 bidder 中 4 个同值 → 80% → is_common=True。"""
    from app.api.routes.compare import compare_metadata

    bidders = [_make_bidder(i, f"B{i}") for i in range(1, 6)]
    docs = [_make_doc(i * 10, i, "commercial") for i in range(1, 6)]
    metas = [
        _make_meta(10, app_name="WPS"),
        _make_meta(20, app_name="WPS"),
        _make_meta(30, app_name="WPS"),
        _make_meta(40, app_name="WPS"),
        _make_meta(50, app_name="Word"),
    ]

    mock_session = AsyncMock()

    with patch("app.api.routes.compare._visible_project", new_callable=AsyncMock):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result(bidders),
            _db_result(docs),
            _db_result(metas),
        ])

        user = AsyncMock()
        resp = await compare_metadata(
            project_id=1, version=None,
            session=mock_session, user=user,
        )

    app_row = [f for f in resp.fields if f.field_name == "app_name"][0]
    wps_cells = [v for v in app_row.values if v.value == "WPS"]
    assert all(v.is_common is True for v in wps_cells)
    word_cells = [v for v in app_row.values if v.value == "Word"]
    assert all(v.is_common is False for v in word_cells)


@pytest.mark.asyncio
async def test_metadata_no_metadata_bidder():
    """bidder 无 DocumentMetadata → 所有字段 null。"""
    from app.api.routes.compare import compare_metadata

    bidders = [_make_bidder(1, "A")]

    mock_session = AsyncMock()

    with patch("app.api.routes.compare._visible_project", new_callable=AsyncMock):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result(bidders),
            _db_result([]),   # no docs
            _db_result([]),   # no metas
        ])

        user = AsyncMock()
        resp = await compare_metadata(
            project_id=1, version=None,
            session=mock_session, user=user,
        )

    for field in resp.fields:
        assert field.values[0].value is None
        assert field.values[0].is_common is True


@pytest.mark.asyncio
async def test_metadata_empty_project():
    """无 bidder → 空响应。"""
    from app.api.routes.compare import compare_metadata

    mock_session = AsyncMock()

    with patch("app.api.routes.compare._visible_project", new_callable=AsyncMock):
        mock_session.execute = AsyncMock(side_effect=[
            _db_result([]),
        ])

        user = AsyncMock()
        resp = await compare_metadata(
            project_id=1, version=None,
            session=mock_session, user=user,
        )

    assert resp.bidders == []
    assert resp.fields == []
