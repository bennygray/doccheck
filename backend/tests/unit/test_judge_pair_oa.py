"""L1 - judge.py pair 维度 OA 聚合行写入 (DEF-OA)

验证:
- judge_and_create_report 完成后 overall_analyses 有 11 行
- pair 类 OA 行 evidence_json 结构正确
- 重复调用幂等(OA 行不重复)
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.analysis_report import AnalysisReport
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.services.detect.judge import PAIR_DIMENSIONS, judge_and_create_report


def _pc(dim: str, score: float, *, ironclad: bool = False):
    """构造一个 PairComparison stub (SimpleNamespace 避免 SQLAlchemy instrumentation)。"""
    return SimpleNamespace(
        project_id=1,
        version=1,
        bidder_a_id=10,
        bidder_b_id=20,
        dimension=dim,
        score=Decimal(str(score)),
        is_ironclad=ironclad,
        evidence_json={},
    )


def _oa(dim: str, score: float, evidence: dict | None = None):
    """构造一个 OverallAnalysis stub (SimpleNamespace)。"""
    return SimpleNamespace(
        project_id=1,
        version=1,
        dimension=dim,
        score=Decimal(str(score)),
        evidence_json=evidence or {},
        manual_review_json=None,
    )


class _FakeSession:
    """收集 add/flush 调用的 fake session。"""

    def __init__(self, existing_pcs: list, existing_oas: list, existing_report=None):
        self._pcs = existing_pcs
        self._oas = existing_oas
        self._existing_report = existing_report
        self.added: list = []
        self._project = SimpleNamespace(
            id=1, name="test", status="analyzing", risk_level=None
        )

    async def execute(self, stmt):
        """根据查询目标返回不同结果。"""
        # 判断查询的 model
        stmt_str = str(stmt)
        if "analysis_reports" in stmt_str:
            return _ScalarResult(self._existing_report)
        if "pair_comparisons" in stmt_str:
            return _ScalarsResult(self._pcs)
        if "overall_analyses" in stmt_str:
            return _ScalarsResult(self._oas)
        if "bidders" in stmt_str:
            return _ScalarsResult([])
        return _ScalarResult(None)

    async def get(self, model, pk):
        return self._project

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


class _ScalarResult:
    def __init__(self, val):
        self._val = val

    def scalar_one_or_none(self):
        return self._val


class _ScalarsResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


@pytest.fixture
def _mock_session_and_deps():
    """Patch async_session + progress_broker + _run_l9。"""
    pcs = [
        _pc("text_similarity", 60.0),
        _pc("section_similarity", 55.0),
        _pc("structure_similarity", 100.0, ironclad=True),
        _pc("metadata_author", 100.0, ironclad=True),
        _pc("metadata_time", 80.0),
        _pc("metadata_machine", 90.0),
        _pc("price_consistency", 100.0, ironclad=True),
    ]
    oas = [
        _oa("error_consistency", 40.0, {"has_iron_evidence": False}),
        _oa("price_anomaly", 0.0, {"has_iron_evidence": False}),
        _oa("style", 30.0, {"has_iron_evidence": False}),
        _oa("image_reuse", 0.0, {"has_iron_evidence": False}),
    ]
    session = _FakeSession(pcs, oas)

    return pcs, oas, session


@pytest.mark.asyncio
async def test_pair_oa_rows_written(_mock_session_and_deps):
    """3.1: judge_and_create_report 后 added 中包含 7 个 pair OA + 1 个 AR = 8 个对象。"""
    pcs, oas, session = _mock_session_and_deps

    async def _fake_l9(*args, **kwargs):
        return None, None

    with (
        patch("app.services.detect.judge.async_session") as mock_ctx,
        patch("app.services.detect.judge._run_l9", _fake_l9),
        patch("app.services.detect.judge.progress_broker") as mock_broker,
    ):
        mock_broker.publish = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await judge_and_create_report(1, 1)

    # 分类 added 对象
    added_oas = [o for o in session.added if isinstance(o, OverallAnalysis)]
    added_ars = [o for o in session.added if isinstance(o, AnalysisReport)]

    # 7 个 pair 维度的 OA 行
    assert len(added_oas) == 7, f"Expected 7 pair OA rows, got {len(added_oas)}"

    # 加上原有 4 个 global OA = 11 维度
    all_dims = {oa.dimension for oa in oas} | {oa.dimension for oa in added_oas}
    assert len(all_dims) == 11

    # 有 1 个 AnalysisReport
    assert len(added_ars) == 1


@pytest.mark.asyncio
async def test_pair_oa_evidence_structure(_mock_session_and_deps):
    """3.2: pair OA 的 evidence_json 包含 source/best_score/has_iron_evidence/pair_count/ironclad_pair_count。"""
    pcs, oas, session = _mock_session_and_deps

    async def _fake_l9(*args, **kwargs):
        return None, None

    with (
        patch("app.services.detect.judge.async_session") as mock_ctx,
        patch("app.services.detect.judge._run_l9", _fake_l9),
        patch("app.services.detect.judge.progress_broker") as mock_broker,
    ):
        mock_broker.publish = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await judge_and_create_report(1, 1)

    added_oas = [o for o in session.added if isinstance(o, OverallAnalysis)]

    # 检查 text_similarity OA
    ts_oa = next(o for o in added_oas if o.dimension == "text_similarity")
    ev = ts_oa.evidence_json
    assert ev["source"] == "pair_aggregation"
    assert ev["best_score"] == 60.0
    assert ev["has_iron_evidence"] is False
    assert ev["pair_count"] == 1
    assert ev["ironclad_pair_count"] == 0

    # 检查 structure_similarity OA (ironclad)
    ss_oa = next(o for o in added_oas if o.dimension == "structure_similarity")
    ev2 = ss_oa.evidence_json
    assert ev2["has_iron_evidence"] is True
    assert ev2["ironclad_pair_count"] == 1
    assert float(ss_oa.score) == 100.0


@pytest.mark.asyncio
async def test_pair_oa_idempotent(_mock_session_and_deps):
    """3.3: 如果 OA 行已存在(text_similarity),不重复写入。"""
    pcs, oas, session = _mock_session_and_deps
    # 模拟 text_similarity 已有 OA 行
    oas.append(_oa("text_similarity", 60.0, {"source": "pair_aggregation"}))

    async def _fake_l9(*args, **kwargs):
        return None, None

    with (
        patch("app.services.detect.judge.async_session") as mock_ctx,
        patch("app.services.detect.judge._run_l9", _fake_l9),
        patch("app.services.detect.judge.progress_broker") as mock_broker,
    ):
        mock_broker.publish = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await judge_and_create_report(1, 1)

    added_oas = [o for o in session.added if isinstance(o, OverallAnalysis)]
    # text_similarity 已有,应只添加 6 个
    assert len(added_oas) == 6
    dims = [o.dimension for o in added_oas]
    assert "text_similarity" not in dims
