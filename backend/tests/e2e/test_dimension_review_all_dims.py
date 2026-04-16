"""L2 - 维度级复核 API 对全部 11 维度返回 200 (DEF-OA)

验证 judge 补写 pair OA 行后,复核 API 对所有 11 个维度可用。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, text

from app.db.session import async_session
from app.models.analysis_report import AnalysisReport
from app.models.audit_log import AuditLog
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.export_job import ExportJob
from app.models.export_template import ExportTemplate
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.project import Project
from app.models.user import User

from ._c4_helpers import seed_project, seed_user, token_for

ALL_DIMENSIONS = [
    "text_similarity",
    "section_similarity",
    "structure_similarity",
    "metadata_author",
    "metadata_time",
    "metadata_machine",
    "price_consistency",
    "price_anomaly",
    "error_consistency",
    "image_reuse",
    "style",
]


@pytest_asyncio.fixture
async def setup_all_dims(client):
    """Seed project + AR + 11 OA rows (模拟 judge 补写后的状态)。"""
    async with async_session() as s:
        await s.execute(text(
            "TRUNCATE TABLE export_jobs, export_templates, audit_logs, "
            "pair_comparisons, overall_analyses, analysis_reports, "
            "document_texts, document_images, document_metadata, price_items, price_parsing_rules, "
            "bid_documents, bidders, projects, users CASCADE"
        ))
        await s.commit()

    owner = await seed_user("defoa_owner", role="reviewer")
    project = await seed_project(owner_id=owner.id, name="P-defoa")

    async with async_session() as s:
        ar = AnalysisReport(
            project_id=project.id,
            version=1,
            total_score=Decimal("92.00"),
            risk_level="high",
            llm_conclusion="test",
        )
        s.add(ar)
        await s.flush()
        for dim in ALL_DIMENSIONS:
            s.add(
                OverallAnalysis(
                    project_id=project.id,
                    version=1,
                    dimension=dim,
                    score=Decimal("50.00"),
                    evidence_json={"source": "pair_aggregation" if dim in (
                        "text_similarity", "section_similarity", "structure_similarity",
                        "metadata_author", "metadata_time", "metadata_machine",
                        "price_consistency",
                    ) else "agent"},
                )
            )
        await s.commit()

    return {
        "client": client,
        "owner": owner,
        "project_id": project.id,
        "version": 1,
    }


@pytest.mark.asyncio
async def test_all_11_dimensions_reviewable(setup_all_dims):
    """DEF-OA 3.6: 维度级复核 API 对全部 11 维度返回 200。"""
    client = setup_all_dims["client"]
    pid = setup_all_dims["project_id"]
    headers = {"Authorization": f"Bearer {token_for(setup_all_dims['owner'])}"}

    for dim in ALL_DIMENSIONS:
        resp = await client.post(
            f"/api/projects/{pid}/reports/1/dimensions/{dim}/review",
            json={"action": "confirmed", "comment": f"review {dim}"},
            headers=headers,
        )
        assert resp.status_code == 200, f"Dimension {dim}: HTTP {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["dimension"] == dim
        assert body["manual_review_json"]["action"] == "confirmed"
