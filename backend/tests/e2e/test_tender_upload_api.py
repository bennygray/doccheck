"""L2: tender 上传 API (detect-tender-baseline 1.15)。

覆盖 spec file-upload "招标文件上传 API" + "列表与删除 API" Requirement 核心 Scenario:
- 上传 docx 招标文件成功 → 201 + parse_status='pending'
- 项目内 md5 重复 → 409
- 上传 .pdf → 415
- 列表返回未软删的
- 软删除后列表不返回
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.tender_document import TenderDocument

from ._c4_helpers import seed_project

# 真实回归 fixture:用户演示用 模板.zip(全 docx/xlsx, 142KB, libmagic 误判 octet-stream)
# 仅在本地 dev 机器存在该路径时启用,CI/其他机器自动 skip
_REAL_TEMPLATE_ZIP = Path(r"C:\Users\7way\Desktop\测试\模板.zip")


def _build_minimal_docx_bytes() -> bytes:
    """构造一个最小可解析的 docx,返 bytes(单独使用)。"""
    from docx import Document

    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph("招标文件正文段落用于测试 baseline 比对的内容")
    doc.save(buf)
    return buf.getvalue()


def _build_tender_zip_bytes() -> bytes:
    """构造一个含 docx 的 zip 作为 tender 上传(与 bidder 一致只接受压缩包)。"""
    import zipfile

    docx_bytes = _build_minimal_docx_bytes()
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("招标文件.docx", docx_bytes)
    return zip_buf.getvalue()


async def test_upload_tender_docx_returns_201(
    seeded_reviewer, reviewer_token, auth_client
):
    """上传 docx 招标文件 → 201 + parse_status='pending'。"""
    # 关闭异步解析,避免后台协程干扰断言
    os.environ["INFRA_DISABLE_EXTRACT"] = "1"
    try:
        project = await seed_project(owner_id=seeded_reviewer.id, name="P1")
        client = await auth_client(reviewer_token)

        zip_bytes = _build_tender_zip_bytes()
        r = await client.post(
            f"/api/projects/{project.id}/tender/",
            files={
                "file": (
                    "招标文件.zip",
                    zip_bytes,
                    "application/zip",
                )
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["file_name"] == "招标文件.zip"
        assert body["parse_status"] == "pending"
        assert isinstance(body["tender_id"], int)

        # DB 验证
        async with async_session() as s:
            row = (
                await s.execute(
                    select(TenderDocument).where(
                        TenderDocument.id == body["tender_id"]
                    )
                )
            ).scalar_one()
            assert row.project_id == project.id
            assert row.parse_status == "pending"
            assert row.deleted_at is None
            assert row.segment_hashes == []
            assert row.boq_baseline_hashes == []
    finally:
        os.environ.pop("INFRA_DISABLE_EXTRACT", None)


async def test_upload_tender_duplicate_md5_returns_409(
    seeded_reviewer, reviewer_token, auth_client
):
    """同 project 内同 md5 重复上传 → 409。"""
    os.environ["INFRA_DISABLE_EXTRACT"] = "1"
    try:
        project = await seed_project(owner_id=seeded_reviewer.id, name="P1")
        client = await auth_client(reviewer_token)

        zip_bytes = _build_tender_zip_bytes()
        r1 = await client.post(
            f"/api/projects/{project.id}/tender/",
            files={"file": ("a.zip", zip_bytes, "application/zip")},
        )
        assert r1.status_code == 201, r1.text

        # 同样 bytes (md5 相同) 第二次上传 → 409
        r2 = await client.post(
            f"/api/projects/{project.id}/tender/",
            files={"file": ("a-copy.zip", zip_bytes, "application/zip")},
        )
        assert r2.status_code == 409
    finally:
        os.environ.pop("INFRA_DISABLE_EXTRACT", None)


async def test_upload_tender_pdf_returns_415(
    seeded_reviewer, reviewer_token, auth_client
):
    """上传 .pdf → 415(本期不支持 PDF 招标文件)。"""
    os.environ["INFRA_DISABLE_EXTRACT"] = "1"
    try:
        project = await seed_project(owner_id=seeded_reviewer.id, name="P1")
        client = await auth_client(reviewer_token)

        r = await client.post(
            f"/api/projects/{project.id}/tender/",
            files={"file": ("file.pdf", b"%PDF-1.4 fake content", "application/pdf")},
        )
        assert r.status_code == 415, r.text
    finally:
        os.environ.pop("INFRA_DISABLE_EXTRACT", None)


@pytest.mark.skipif(
    not _REAL_TEMPLATE_ZIP.exists(),
    reason="real-world 模板.zip fixture 不存在(非本地 dev 机器),跳过",
)
async def test_upload_tender_real_template_zip_passes_validator_regression(
    seeded_reviewer, reviewer_token, auth_client
):
    """回归:真 模板.zip(libmagic 返 application/octet-stream)应能通过 validator。

    Bug:小型 zip 全 docx/xlsx 时 libmagic 不识别返 octet-stream,validator 之前
    直接判错。修复后 octet-stream 走字节头 fallback,PK\\x03\\x04 命中 → 通过。
    """
    os.environ["INFRA_DISABLE_EXTRACT"] = "1"
    try:
        project = await seed_project(owner_id=seeded_reviewer.id, name="P-real")
        client = await auth_client(reviewer_token)

        zip_bytes = _REAL_TEMPLATE_ZIP.read_bytes()
        r = await client.post(
            f"/api/projects/{project.id}/tender/",
            files={"file": ("模板.zip", zip_bytes, "application/zip")},
        )
        assert r.status_code == 201, r.text
        assert r.json()["file_name"] == "模板.zip"
    finally:
        os.environ.pop("INFRA_DISABLE_EXTRACT", None)


async def test_list_tender_returns_only_active(
    seeded_reviewer, reviewer_token, auth_client
):
    """列表只返回 deleted_at IS NULL 的招标文件。"""
    os.environ["INFRA_DISABLE_EXTRACT"] = "1"
    try:
        project = await seed_project(owner_id=seeded_reviewer.id, name="P1")
        client = await auth_client(reviewer_token)

        # 上传 1 份
        zip_bytes = _build_tender_zip_bytes()
        r1 = await client.post(
            f"/api/projects/{project.id}/tender/",
            files={"file": ("a.zip", zip_bytes, "application/zip")},
        )
        tid = r1.json()["tender_id"]

        # 列表应有 1 条
        r_list = await client.get(f"/api/projects/{project.id}/tender/")
        assert r_list.status_code == 200
        rows = r_list.json()
        assert len(rows) == 1
        assert rows[0]["id"] == tid

        # 软删除
        r_del = await client.delete(f"/api/projects/{project.id}/tender/{tid}")
        assert r_del.status_code == 204

        # 列表应空
        r_list2 = await client.get(f"/api/projects/{project.id}/tender/")
        assert r_list2.status_code == 200
        assert r_list2.json() == []
    finally:
        os.environ.pop("INFRA_DISABLE_EXTRACT", None)
