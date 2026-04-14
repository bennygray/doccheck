"""DOCX 嵌入图片导出 + md5 + pHash (C5 parser-pipeline US-4.2)

遍历 docx 的 part.related_parts,导出 JPG/PNG/BMP/TIFF 到 imgs/ 目录;
计算 md5 + Pillow 加载 + imagehash.phash。
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {"jpg", "jpeg", "png", "bmp", "tiff", "tif", "gif"}


@dataclass(frozen=True)
class ImageInfo:
    file_path: str
    md5: str
    phash: str
    width: int | None
    height: int | None
    position: str | None = None  # 预留,DOCX 嵌入图统一填 "body"


def extract_images_from_docx(
    docx_path: str | Path, output_dir: str | Path
) -> list[ImageInfo]:
    """导出 DOCX 嵌入图片;返回每张图的元信息。异常不抛,单图失败跳过。"""
    from docx import Document

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    doc = Document(str(docx_path))
    results: list[ImageInfo] = []
    seen_md5: set[str] = set()

    for rel_id, rel in doc.part.rels.items():
        if "image" not in rel.reltype:
            continue
        try:
            blob: bytes = rel.target_part.blob
            ext = _ext_from_part(rel.target_part)
            if ext not in _IMAGE_EXTS:
                continue
            md5 = hashlib.md5(blob).hexdigest()
            if md5 in seen_md5:
                continue  # 同一 docx 内重复引用同图
            seen_md5.add(md5)
            info = _process_image_blob(blob, md5, ext, out)
            if info:
                results.append(info)
        except Exception as e:  # pragma: no cover - 单图失败跳过
            logger.warning("image extract failed rel=%s: %s", rel_id, e)

    return results


def _process_image_blob(
    blob: bytes, md5: str, ext: str, out: Path
) -> ImageInfo | None:
    from PIL import Image
    import imagehash

    try:
        img = Image.open(io.BytesIO(blob))
        width, height = img.size
        phash = str(imagehash.phash(img))  # 16 字符 hex(64 bit)
    except Exception as e:
        logger.warning("image decode failed md5=%s: %s", md5, e)
        return None

    file_path = out / f"{md5}.{ext}"
    file_path.write_bytes(blob)
    return ImageInfo(
        file_path=str(file_path),
        md5=md5,
        phash=phash,
        width=width,
        height=height,
        position="body",
    )


def _ext_from_part(part) -> str:
    """从 docx part 的 content_type 或 partname 推扩展名。"""
    ct = (part.content_type or "").lower()
    if "jpeg" in ct or "jpg" in ct:
        return "jpg"
    if "png" in ct:
        return "png"
    if "bmp" in ct:
        return "bmp"
    if "tiff" in ct:
        return "tiff"
    if "gif" in ct:
        return "gif"
    # fallback: 从 partname 后缀
    name = str(getattr(part, "partname", "")).lower()
    for ext in _IMAGE_EXTS:
        if name.endswith("." + ext):
            return ext
    return ""


__all__ = ["extract_images_from_docx", "ImageInfo"]
