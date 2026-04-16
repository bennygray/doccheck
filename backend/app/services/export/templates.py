"""模板加载 + 回退内置 (C15 report-export, D7)

load_template(template_id | None) 返回磁盘路径:
- None → 内置 default.docx
- 指定 id 但模板不存在 / 文件丢失 → 抛 TemplateLoadError(由 worker 捕获 fallback)
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.export_template import ExportTemplate


class TemplateLoadError(RuntimeError):
    """Raised when a user template fails to load; worker fallbacks to builtin."""


# 本模块目录下的 templates/default.docx 为内置模板
BUILTIN_TEMPLATE_PATH = Path(__file__).parent / "templates" / "default.docx"


def builtin_template_path() -> Path:
    """返回内置模板文件路径(docxtpl 可直接加载)。"""
    return BUILTIN_TEMPLATE_PATH


async def load_template(
    session: AsyncSession, template_id: int | None
) -> Path:
    """加载模板文件路径。None → 内置;异常抛 TemplateLoadError。"""
    if template_id is None:
        path = builtin_template_path()
        if not path.exists():
            raise TemplateLoadError(
                f"builtin template missing: {path}"
            )
        return path

    row = await session.get(ExportTemplate, template_id)
    if row is None:
        raise TemplateLoadError(f"template {template_id} not found in DB")
    path = Path(row.file_path)
    if not path.exists():
        raise TemplateLoadError(
            f"template {template_id} file missing on disk: {row.file_path}"
        )
    return path


__all__ = [
    "TemplateLoadError",
    "BUILTIN_TEMPLATE_PATH",
    "builtin_template_path",
    "load_template",
]
