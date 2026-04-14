"""DOCX/XLSX 元数据提取 (C5 parser-pipeline US-4.2)

读 OOXML 的 docProps/core.xml + docProps/app.xml,提取:
author / last_saved_by / company / created / modified / app_name / app_version。
字段缺失返 None 不抛错。
"""

from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_CORE_NS = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}
_APP_NS = {
    "ap": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
}


@dataclass(frozen=True)
class DocMetadata:
    author: str | None = None
    last_saved_by: str | None = None
    company: str | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    app_name: str | None = None
    app_version: str | None = None
    template: str | None = None


def _parse_iso_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # OOXML 用 ISO8601;Z 结尾需转 +00:00
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def extract_metadata(file_path: str | Path) -> DocMetadata:
    """从 docx/xlsx 抽元数据。任何 IO/解析失败整体返空 DocMetadata(不抛)。"""
    from lxml import etree

    path = Path(file_path)
    try:
        with zipfile.ZipFile(str(path)) as zf:
            core_xml = _read_or_none(zf, "docProps/core.xml")
            app_xml = _read_or_none(zf, "docProps/app.xml")
    except (zipfile.BadZipFile, FileNotFoundError) as e:
        logger.warning("metadata zip open failed %s: %s", path, e)
        return DocMetadata()

    author = None
    last_saved_by = None
    created = None
    modified = None
    if core_xml:
        try:
            root = etree.fromstring(core_xml)
            author = _text(root, "dc:creator", _CORE_NS)
            last_saved_by = _text(root, "cp:lastModifiedBy", _CORE_NS)
            created = _parse_iso_dt(_text(root, "dcterms:created", _CORE_NS))
            modified = _parse_iso_dt(_text(root, "dcterms:modified", _CORE_NS))
        except Exception as e:
            logger.warning("core.xml parse failed: %s", e)

    company = None
    app_name = None
    app_version = None
    template = None
    if app_xml:
        try:
            root = etree.fromstring(app_xml)
            company = _text(root, "ap:Company", _APP_NS)
            app_name = _text(root, "ap:Application", _APP_NS)
            app_version = _text(root, "ap:AppVersion", _APP_NS)
            template = _text(root, "ap:Template", _APP_NS)
        except Exception as e:
            logger.warning("app.xml parse failed: %s", e)

    return DocMetadata(
        author=author,
        last_saved_by=last_saved_by,
        company=company,
        created_at=created,
        modified_at=modified,
        app_name=app_name,
        app_version=app_version,
        template=template,
    )


def _read_or_none(zf: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        return zf.read(name)
    except KeyError:
        return None


def _text(root, xpath: str, ns: dict[str, str]) -> str | None:
    el = root.find(xpath, ns)
    if el is None:
        return None
    t = (el.text or "").strip()
    return t or None


__all__ = ["extract_metadata", "DocMetadata"]
