"""L1 - parser/content/metadata_parser.extract_metadata Template 字段提取 (C10)"""

from __future__ import annotations

import zipfile
from pathlib import Path

from app.services.parser.content.metadata_parser import extract_metadata


_APP_XML_WITH_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>Microsoft Office Word</Application>
  <AppVersion>16.0000</AppVersion>
  <Company>测试公司</Company>
  <Template>Normal.dotm</Template>
</Properties>
"""

_APP_XML_NO_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>Microsoft Office Word</Application>
  <AppVersion>16.0000</AppVersion>
</Properties>
"""

_CORE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:creator>张三</dc:creator>
</cp:coreProperties>
"""


def _make_ooxml_stub(out: Path, app_xml_body: str) -> Path:
    """写一个伪 OOXML(zip 含 docProps/core.xml + app.xml)。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(out), "w") as zf:
        zf.writestr("docProps/core.xml", _CORE_XML)
        zf.writestr("docProps/app.xml", app_xml_body)
    return out


def test_extract_template_present(tmp_path: Path) -> None:
    path = _make_ooxml_stub(tmp_path / "with_tpl.docx", _APP_XML_WITH_TEMPLATE)
    meta = extract_metadata(path)
    assert meta.template == "Normal.dotm"
    assert meta.author == "张三"
    assert meta.app_name == "Microsoft Office Word"


def test_extract_template_absent(tmp_path: Path) -> None:
    path = _make_ooxml_stub(tmp_path / "no_tpl.docx", _APP_XML_NO_TEMPLATE)
    meta = extract_metadata(path)
    assert meta.template is None
    assert meta.app_name == "Microsoft Office Word"


def test_extract_no_app_xml(tmp_path: Path) -> None:
    """app.xml 完全不存在时,template 与 app_* 均 None。"""
    path = tmp_path / "no_app.docx"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(path), "w") as zf:
        zf.writestr("docProps/core.xml", _CORE_XML)
    meta = extract_metadata(path)
    assert meta.template is None
    assert meta.app_name is None
    assert meta.author == "张三"


def test_extract_malformed_zip(tmp_path: Path) -> None:
    """坏的 zip 不抛 — 返空 DocMetadata。"""
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip")
    meta = extract_metadata(path)
    assert meta.template is None
    assert meta.author is None
