"""L1:docx textbox 用 lxml xpath 抽取(parser-accuracy-fixes P2-8)

用 python-docx 构建带 textbox 的 docx 比较繁琐,直接手工构造 zip 格式 docx
(含 word/document.xml 引用 w:txbxContent)。
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import pytest

from app.services.parser.content.docx_parser import extract_docx


# 最小 docx skeleton:只含 document.xml + minimal relationships
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

# 含 textbox 的 document.xml
_DOCUMENT_XML_WITH_TEXTBOX = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
            xmlns:v="urn:schemas-microsoft-com:vml"
            xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
<w:body>
<w:p><w:r><w:t>这是正文一段话</w:t></w:r></w:p>
<w:p>
<w:r>
<mc:AlternateContent>
<mc:Choice Requires="wps">
<w:drawing>
<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
<wp:extent cx="914400" cy="914400"/>
<wp:docPr id="1" name="TextBox 1"/>
<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
<a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
<wps:wsp>
<wps:txbx>
<w:txbxContent>
<w:p><w:r><w:t>盖章处</w:t></w:r></w:p>
<w:p><w:r><w:t>联系电话:12345</w:t></w:r></w:p>
</w:txbxContent>
</wps:txbx>
</wps:wsp>
</a:graphicData>
</a:graphic>
</wp:inline>
</w:drawing>
</mc:Choice>
<mc:Fallback><w:pict><v:rect><v:textbox><w:txbxContent><w:p><w:r><w:t>fallback</w:t></w:r></w:p></w:txbxContent></v:textbox></v:rect></w:pict></mc:Fallback>
</mc:AlternateContent>
</w:r>
</w:p>
</w:body>
</w:document>"""

# 不含 textbox 的最小 document.xml
_DOCUMENT_XML_NO_TEXTBOX = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:r><w:t>只有正文无文本框</w:t></w:r></w:p>
</w:body>
</w:document>"""


def _make_docx(path: Path, document_xml: str) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("word/document.xml", document_xml)
    return path


def test_textbox_extracted_via_lxml_xpath(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """textbox 内容被抽出,无 namespaces kwarg 告警"""
    caplog.set_level(logging.WARNING, logger="app.services.parser.content.docx_parser")
    docx = _make_docx(tmp_path / "with_textbox.docx", _DOCUMENT_XML_WITH_TEXTBOX)
    result = extract_docx(docx)
    # 至少 1 条 body + 1 条 textbox
    locations = [b.location for b in result.blocks]
    assert "textbox" in locations, f"未找到 textbox block;locations={locations}"

    textbox_block = next(b for b in result.blocks if b.location == "textbox")
    assert "盖章处" in textbox_block.text
    assert "联系电话:12345" in textbox_block.text

    # 关键:不再有 BaseOxmlElement.xpath namespaces 告警
    warnings_msg = [r.message for r in caplog.records if r.levelname == "WARNING"]
    for w in warnings_msg:
        assert "BaseOxmlElement" not in w, f"仍出现老告警: {w}"
        assert "namespaces" not in w, f"仍出现老告警: {w}"
    # result.warnings 也应无 textbox 相关错
    for w in result.warnings:
        assert "textbox" not in w.lower(), f"textbox warning: {w}"


def test_no_textbox_docx_ok(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """不含 textbox 的 docx 不报错,也不出 textbox block"""
    caplog.set_level(logging.WARNING)
    docx = _make_docx(tmp_path / "no_textbox.docx", _DOCUMENT_XML_NO_TEXTBOX)
    result = extract_docx(docx)
    locations = [b.location for b in result.blocks]
    assert "textbox" not in locations
    # 也无 textbox warning
    for w in result.warnings:
        assert "textbox" not in w.lower()
    # 正文被抽出
    body_blocks = [b for b in result.blocks if b.location == "body"]
    assert len(body_blocks) >= 1
    assert "只有正文" in body_blocks[0].text
