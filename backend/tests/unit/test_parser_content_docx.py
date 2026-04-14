"""L1 - parser/content/docx_parser 单元测试 (C5 §9.1)"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.parser.content.docx_parser import extract_docx
from tests.fixtures.doc_fixtures import make_real_docx


def test_extract_body_paragraphs(tmp_path: Path) -> None:
    path = make_real_docx(
        tmp_path / "a.docx",
        body_paragraphs=["段一", "段二", "段三"],
    )
    result = extract_docx(path)
    body_blocks = [b for b in result.blocks if b.location == "body"]
    assert len(body_blocks) == 3
    assert [b.text for b in body_blocks] == ["段一", "段二", "段三"]


def test_extract_empty_paragraphs_skipped(tmp_path: Path) -> None:
    path = make_real_docx(
        tmp_path / "b.docx",
        body_paragraphs=["有内容", "", "   ", "又有"],
    )
    result = extract_docx(path)
    body_blocks = [b for b in result.blocks if b.location == "body"]
    assert len(body_blocks) == 2  # 空与纯空格段过滤


def test_extract_header_footer(tmp_path: Path) -> None:
    path = make_real_docx(
        tmp_path / "c.docx",
        body_paragraphs=["正文"],
        header_text="页眉某公司",
        footer_text="第 1 页",
    )
    result = extract_docx(path)
    locs = {b.location for b in result.blocks}
    assert "header" in locs
    assert "footer" in locs
    header_text = next(b.text for b in result.blocks if b.location == "header")
    assert "页眉" in header_text


def test_extract_table_rows(tmp_path: Path) -> None:
    path = make_real_docx(
        tmp_path / "d.docx",
        body_paragraphs=["正文"],
        table_rows=[["项目", "数量"], ["A", "1"], ["B", "2"]],
    )
    result = extract_docx(path)
    table_blocks = [b for b in result.blocks if b.location == "table_row"]
    assert len(table_blocks) == 3
    assert "项目" in table_blocks[0].text
    assert "A" in table_blocks[1].text


def test_paragraph_index_monotonic(tmp_path: Path) -> None:
    path = make_real_docx(
        tmp_path / "e.docx",
        body_paragraphs=["一", "二", "三"],
    )
    result = extract_docx(path)
    indices = [b.paragraph_index for b in result.blocks]
    assert indices == sorted(indices)
    # 不同 location 的索引都在单一 counter
    assert len(set(indices)) == len(indices)


def test_broken_docx_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"PK\x03\x04notadocx")
    with pytest.raises(Exception):
        extract_docx(bad)
