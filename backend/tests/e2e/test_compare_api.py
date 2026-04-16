"""L2 — C16 compare-view API E2E 测试。

3 Scenario:
- S1 文本对比:seed bidder+document+text+pair → GET /compare/text → 验证段落+matches
- S2 报价对比:seed bidder+price_items → GET /compare/price → 验证矩阵+totals
- S3 元数据对比:seed bidder+document+metadata → GET /compare/metadata → 验证字段+着色
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.session import async_session
from app.models.agent_task import AgentTask
from app.models.analysis_report import AnalysisReport
from app.models.audit_log import AuditLog
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_metadata import DocumentMetadata
from app.models.document_text import DocumentText
from app.models.export_job import ExportJob
from app.models.export_template import ExportTemplate
from app.models.overall_analysis import OverallAnalysis
from app.models.pair_comparison import PairComparison
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project
from app.models.user import User

from ._c4_helpers import seed_project, seed_user, token_for


@pytest_asyncio.fixture
async def setup(client):
    """Clean + seed:2 bidders, docs, texts, prices, metadata, AR, PC."""
    async with async_session() as s:
        for M in (
            ExportJob, ExportTemplate, AuditLog, AgentTask,
            PairComparison, OverallAnalysis, AnalysisReport,
            PriceItem, PriceParsingRule,
            DocumentMetadata, DocumentText, BidDocument,
            Bidder, Project, User,
        ):
            await s.execute(delete(M))
        await s.commit()

    owner = await seed_user("c16_owner", role="reviewer")
    project = await seed_project(owner_id=owner.id, name="P-c16")

    async with async_session() as s:
        b1 = Bidder(project_id=project.id, name="甲公司", parse_status="completed")
        b2 = Bidder(project_id=project.id, name="乙公司", parse_status="completed")
        s.add_all([b1, b2])
        await s.flush()

        # 文档
        doc1 = BidDocument(
            bidder_id=b1.id, file_name="商务标.docx", file_path="/tmp/a.docx",
            file_size=1000, file_type="docx", md5="a" * 32,
            file_role="commercial", source_archive="a.zip",
        )
        doc2 = BidDocument(
            bidder_id=b2.id, file_name="商务标.docx", file_path="/tmp/b.docx",
            file_size=1000, file_type="docx", md5="b" * 32,
            file_role="commercial", source_archive="b.zip",
        )
        s.add_all([doc1, doc2])
        await s.flush()

        # 段落
        for i in range(5):
            s.add(DocumentText(
                bid_document_id=doc1.id, paragraph_index=i,
                text=f"甲公司段落{i}", location="body",
            ))
            s.add(DocumentText(
                bid_document_id=doc2.id, paragraph_index=i,
                text=f"乙公司段落{i}", location="body",
            ))

        # 元数据
        s.add(DocumentMetadata(
            bid_document_id=doc1.id, author="张三",
            last_saved_by="张三", company="甲集团",
            app_name="WPS Office", app_version="11.1",
            template="Normal.dotm",
        ))
        s.add(DocumentMetadata(
            bid_document_id=doc2.id, author="张三",
            last_saved_by="李四", company="乙集团",
            app_name="WPS Office", app_version="11.1",
            template="Normal.dotm",
        ))

        # 报价规则(FK 依赖)
        rule = PriceParsingRule(
            project_id=project.id,
            sheet_name="Sheet1",
            header_row=0,
            column_mapping={"item_name": 0, "unit_price": 1},
        )
        s.add(rule)
        await s.flush()

        # 报价项
        for idx, (name, up_a, up_b) in enumerate([
            ("水泥", 100, 100),
            ("钢筋", 200, 300),
            ("砂石", 50, 51),
        ]):
            s.add(PriceItem(
                bidder_id=b1.id, price_parsing_rule_id=rule.id,
                sheet_name="Sheet1", row_index=idx,
                item_name=name, unit="吨",
                unit_price=Decimal(str(up_a)),
                total_price=Decimal(str(up_a * 10)),
            ))
            s.add(PriceItem(
                bidder_id=b2.id, price_parsing_rule_id=rule.id,
                sheet_name="Sheet1", row_index=idx,
                item_name=name, unit="吨",
                unit_price=Decimal(str(up_b)),
                total_price=Decimal(str(up_b * 10)),
            ))

        # AnalysisReport
        ar = AnalysisReport(
            project_id=project.id, version=1,
            total_score=Decimal("65.00"), risk_level="medium",
            llm_conclusion="",
        )
        s.add(ar)
        await s.flush()

        # PairComparison (text_similarity)
        s.add(PairComparison(
            project_id=project.id, version=1,
            dimension="text_similarity",
            bidder_a_id=b1.id, bidder_b_id=b2.id,
            score=Decimal("72.00"),
            evidence_json={
                "doc_role": "commercial",
                "doc_id_a": doc1.id,
                "doc_id_b": doc2.id,
                "samples": [
                    {"a_idx": 0, "b_idx": 0, "sim": 0.92, "label": "plagiarism",
                     "a_text": "甲公司段落0", "b_text": "乙公司段落0"},
                    {"a_idx": 2, "b_idx": 2, "sim": 0.71, "label": "template",
                     "a_text": "甲公司段落2", "b_text": "乙公司段落2"},
                ],
            },
        ))

        await s.commit()

        return {
            "owner": owner,
            "project_id": project.id,
            "b1_id": b1.id,
            "b2_id": b2.id,
        }


@pytest.mark.asyncio
async def test_compare_text(client, setup):
    """S1:文本对比全链路。"""
    d = setup
    tok = token_for(d["owner"])
    pid = d["project_id"]

    resp = await client.get(
        f"/api/projects/{pid}/compare/text",
        params={"bidder_a": d["b1_id"], "bidder_b": d["b2_id"], "version": 1},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["bidder_a_id"] == d["b1_id"]
    assert body["bidder_b_id"] == d["b2_id"]
    assert body["doc_role"] == "commercial"
    assert len(body["left_paragraphs"]) == 5
    assert len(body["right_paragraphs"]) == 5
    assert len(body["matches"]) == 2
    assert body["matches"][0]["sim"] == 0.92
    assert body["matches"][0]["label"] == "plagiarism"
    assert body["available_roles"] == ["commercial"]
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_compare_price(client, setup):
    """S2:报价对比全链路。"""
    d = setup
    tok = token_for(d["owner"])
    pid = d["project_id"]

    resp = await client.get(
        f"/api/projects/{pid}/compare/price",
        params={"version": 1},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["bidders"]) == 2
    assert body["bidders"][0]["bidder_name"] == "甲公司"
    assert len(body["items"]) == 3

    # 水泥:两家都 100,偏差 0%
    cement = [r for r in body["items"] if r["item_name"] == "水泥"][0]
    assert cement["has_anomaly"] is True
    assert cement["mean_unit_price"] == 100.0

    # totals
    assert len(body["totals"]) == 2
    # 甲: (100+200+50)*10=3500
    assert body["totals"][0]["total_price"] == 3500.0
    # 乙: (100+300+51)*10=4510
    assert body["totals"][1]["total_price"] == 4510.0


@pytest.mark.asyncio
async def test_compare_metadata(client, setup):
    """S3:元数据对比全链路。"""
    d = setup
    tok = token_for(d["owner"])
    pid = d["project_id"]

    resp = await client.get(
        f"/api/projects/{pid}/compare/metadata",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["bidders"]) == 2
    assert len(body["fields"]) == 8

    # author:both "张三" → same color_group
    author = [f for f in body["fields"] if f["field_name"] == "author"][0]
    assert author["values"][0]["value"] == "张三"
    assert author["values"][1]["value"] == "张三"
    assert author["values"][0]["color_group"] == author["values"][1]["color_group"]

    # template:both "Normal.dotm" → same color_group
    tmpl = [f for f in body["fields"] if f["field_name"] == "template"][0]
    assert tmpl["values"][0]["value"] == "Normal.dotm"
    assert tmpl["values"][0]["color_group"] == tmpl["values"][1]["color_group"]

    # app_name:both "WPS Office" → 100% frequency → is_common
    app = [f for f in body["fields"] if f["field_name"] == "app_name"][0]
    assert app["values"][0]["is_common"] is True
