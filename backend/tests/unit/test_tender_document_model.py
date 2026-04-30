"""L1 - TenderDocument 模型 + parse_tender_archive 单测 (detect-tender-baseline 1.12)

覆盖 spec detect-framework "TenderDocument 数据模型" Requirement Scenarios + 1.8b
parse_tender_archive 行为(短段守门 / 去重 / fail-soft)。

DB 级 unique constraint / 软删除 由 L2 e2e 覆盖(test_tender_upload_api.py)。
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from app.models.tender_document import (
    PARSE_STATUS_VALUES,
    TenderDocument,
)


# ============================================================ 模型字段


def test_tender_document_required_columns():
    """TenderDocument 必须含的字段 + JSONB hash 集合默认 []。"""
    cols = {c.name for c in TenderDocument.__table__.columns}
    required = {
        "id",
        "project_id",
        "file_name",
        "file_path",
        "file_size",
        "md5",
        "parse_status",
        "parse_error",
        "segment_hashes",
        "boq_baseline_hashes",
        "created_at",
        "deleted_at",
    }
    assert required.issubset(cols), f"missing columns: {required - cols}"


def test_tender_document_unique_constraint_project_md5():
    """UniqueConstraint(project_id, md5) 项目内去重(D1)。"""
    constraints = TenderDocument.__table_args__
    uq_names = {
        c.name for c in constraints if hasattr(c, "name") and "uq" in c.name
    }
    assert "uq_tender_documents_project_md5" in uq_names


def test_parse_status_values_enum():
    """PARSE_STATUS_VALUES 应用层枚举(与 BidDocument 风格一致,不加 DB CHECK)。"""
    assert PARSE_STATUS_VALUES == frozenset(
        {"pending", "parsing", "extracted", "failed"}
    )


# ============================================================ parse_tender_archive 行为


def _build_fake_docx_zip(tmp_path: Path, segments: list[str]) -> Path:
    """构造一个最小可解析的 docx 文件(单段或多段)。"""
    from docx import Document

    docx_path = tmp_path / "test.docx"
    doc = Document()
    for text in segments:
        doc.add_paragraph(text)
    doc.save(str(docx_path))
    return docx_path


def test_parse_tender_archive_docx_extracts_segment_hashes(tmp_path: Path):
    """解析单 docx,segment_hashes 包含期望段 hash。"""
    from app.services.extract._tender_parser import parse_tender_archive

    docx_path = _build_fake_docx_zip(
        tmp_path,
        [
            "锂源（江苏）科技有限公司",  # 12 字 ≥5 → hash
            "abc",  # 3 字 < 5 → skip(短段守门)
            "投标文件模板正文段落内容用于 baseline 比对",  # 长段 → hash
        ],
    )
    seg_hashes, boq_hashes = parse_tender_archive(str(docx_path))
    # 12 字 + 长段 = 2 个 hash;3 字段被守门
    assert len(seg_hashes) == 2
    assert len(boq_hashes) == 0  # docx 不产 BOQ hash


def test_parse_tender_archive_dedup_within_archive(tmp_path: Path):
    """同 docx 多段相同文本 → 集合去重(只 1 个 hash)。"""
    from app.services.extract._tender_parser import parse_tender_archive

    docx_path = _build_fake_docx_zip(
        tmp_path,
        [
            "重复段落内容内容内容",
            "重复段落内容内容内容",
            "重复段落内容内容内容",
        ],
    )
    seg_hashes, _ = parse_tender_archive(str(docx_path))
    assert len(seg_hashes) == 1


def test_parse_tender_archive_zip_combines_multiple_files(tmp_path: Path):
    """zip 内多 docx,segment_hashes 合并去重。"""
    from app.services.extract._tender_parser import parse_tender_archive

    # 构造 2 docx 各 1 段不同内容
    d1_dir = tmp_path / "d1"
    d1_dir.mkdir()
    docx1 = _build_fake_docx_zip(d1_dir, ["第一份招标文件正文段一段一"])
    d2_dir = tmp_path / "d2"
    d2_dir.mkdir()
    docx2 = _build_fake_docx_zip(d2_dir, ["第二份招标文件正文段二段二"])

    zip_path = tmp_path / "tender.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(docx1, arcname="附件1.docx")
        zf.write(docx2, arcname="附件2.docx")

    seg_hashes, _ = parse_tender_archive(str(zip_path))
    assert len(seg_hashes) == 2  # 两份文件各 1 段不同内容


def test_parse_tender_archive_unsupported_extension_raises(tmp_path: Path):
    """非 docx/xlsx/zip → ValueError(spec file-upload 415)。"""
    from app.services.extract._tender_parser import parse_tender_archive

    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(ValueError, match="unsupported"):
        parse_tender_archive(str(pdf_path))


def test_parse_tender_archive_missing_file_raises(tmp_path: Path):
    """文件不存在 → FileNotFoundError(fail-soft 由 _extract_tender_archive 兜底)。"""
    from app.services.extract._tender_parser import parse_tender_archive

    with pytest.raises(FileNotFoundError):
        parse_tender_archive(str(tmp_path / "nonexistent.docx"))
