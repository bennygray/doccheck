"""Tender 解析独立路径(detect-tender-baseline 1.8b minimal)。

职责:把一份招标文件(zip / docx / xlsx)解析成两个 hash 集合:
- segment_hashes: 段级 sha256(归一化后段文本),供 text_similarity / section_similarity baseline
- boq_baseline_hashes: BOQ 项级 sha256(项目名+描述+单位+工程量),供 price_consistency baseline

**MUST NOT** 调用任何 LLM(file_role 固定 'tender',跳过 role_classifier)。
**MUST NOT** 写 DocumentText/DocumentSheet 表(简化决策:tender 段 hash 直接存 TenderDocument JSONB)。

设计要点(详见 openspec/changes/detect-tender-baseline/design.md D7 + apply 简化):
- zip 包内多 docx/xlsx 时合并所有 hash 到同一集合(tender baseline 是项目级的,不区分文件归属)
- 短段(归一化 < 5 字)NULL 守门 → 不进集合(spec detect-framework "短段守门")
- BOQ 行 < 3 个非空 cell → 跳过(纯标题/合计/备注行不进 BOQ baseline)
- 工程量精度归一化:Decimal(str).normalize() 去尾随零("1.0" / "1" / "1.000" hash 一致)
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.services.detect.agents.text_sim_impl.tfidf import _normalize

logger = logging.getLogger(__name__)

# 短段守门(spec detect-framework 段长度 < 5 字 NULL 守门;归一化后字符长度)
_MIN_SEGMENT_LEN = 5

# BOQ 行有效性门槛:< 3 个非空 cell 视为标题/合计/备注,不进 BOQ baseline
_MIN_BOQ_ROW_NONEMPTY_CELLS = 3


def _segment_hash(text: str) -> str | None:
    """归一化(NFKC + \\s+→' ' + strip)+ sha256;短段返 None。"""
    norm = _normalize(text)
    if len(norm) < _MIN_SEGMENT_LEN:
        return None
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _decimal_normalize(value: object) -> str:
    """工程量精度归一化:'1' / '1.0' / '1.000' 都返回 '1'。

    非数值或空值返回 ''(参与联合 hash 时仍能比对)。
    """
    if value is None or value == "":
        return ""
    try:
        d = Decimal(str(value).strip())
        # normalize() 去尾随零;转 str 处理 1E+1 这种科学记数法
        norm = d.normalize()
        # Decimal('1E+1') → str → '1E+1';要的是 '10'。用 +0 强制展开
        if "E" in str(norm) or "e" in str(norm):
            norm = norm.quantize(Decimal(1)) if norm == norm.to_integral() else norm
        return str(norm) if norm == norm.normalize() else str(d)
    except (InvalidOperation, ValueError):
        return str(value).strip()


def _boq_row_hash(
    item_name: object, description: object, unit: object, quantity: object
) -> str | None:
    """BOQ 项级 hash:sha256(项目名+描述+单位+Decimal.normalize(工程量))。

    设计 D5:**不含**单价/合价/总价(那是应标方差异化输入)。
    任一关键字段为空时返 None(行不完整,不进 baseline)。
    """
    name_norm = _normalize(str(item_name) if item_name is not None else "")
    desc_norm = _normalize(str(description) if description is not None else "")
    unit_norm = _normalize(str(unit) if unit is not None else "")
    qty_norm = _decimal_normalize(quantity)
    # 项目名 + 工程量为空时不可比对
    if not name_norm or not qty_norm:
        return None
    key = f"{name_norm}|{desc_norm}|{unit_norm}|{qty_norm}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _extract_docx_segments(file_path: Path) -> list[str]:
    """从 docx 提取所有段文本(body + table_row + header + footer)。

    复用 parser/content/docx_parser.py:extract_docx,返回非空段文本列表。
    """
    from app.services.parser.content.docx_parser import extract_docx

    result = extract_docx(file_path)
    return [block.text for block in result.blocks if block.text.strip()]


def _extract_xlsx_segments_and_boq(
    file_path: Path,
) -> tuple[list[str], list[str]]:
    """从 xlsx 提取段文本(每行合并)+ BOQ 项级 hash 集合。

    BOQ 列假设(简化版,实测模板验证):
    - 跳过前 N 个 header 行(用 row 非空 cell 数量 < _MIN_BOQ_ROW_NONEMPTY_CELLS 过滤)
    - 取每行前 4 个非空列作为 (item_name, description, unit, quantity) 联合 hash
    - 实际客户场景列布局可能不同,L2 实测调优;本期 best-effort 方案
    """
    from app.services.parser.content.xlsx_parser import extract_xlsx

    result = extract_xlsx(file_path)
    segments: list[str] = []
    boq_hashes: list[str] = []
    seen_boq: set[str] = set()

    for sheet in result.sheets:
        # 段级:每行合并为一条文本(给 segment_similarity 用)
        for row_idx, row in enumerate(sheet.rows):
            non_empty = [c for c in row if c is not None and str(c).strip()]
            if not non_empty:
                continue
            row_text = " | ".join(str(c).strip() for c in non_empty)
            if row_text:
                segments.append(row_text)

            # BOQ 项级:< 3 个非空 cell 跳过(标题/合计/备注)
            if len(non_empty) < _MIN_BOQ_ROW_NONEMPTY_CELLS:
                continue
            # 取前 4 列作为 (项目名, 描述, 单位, 工程量) 联合
            # 注:实际 xlsx 列布局各招标方不同;L2 实测调优,本期简化
            cells = list(row)
            item_name = cells[0] if len(cells) > 0 else None
            description = cells[1] if len(cells) > 1 else None
            unit = cells[2] if len(cells) > 2 else None
            quantity = cells[3] if len(cells) > 3 else None
            h = _boq_row_hash(item_name, description, unit, quantity)
            if h is not None and h not in seen_boq:
                seen_boq.add(h)
                boq_hashes.append(h)

    return segments, boq_hashes


def parse_tender_archive(file_path: str) -> tuple[list[str], list[str]]:
    """解析 tender 归档(zip / docx / xlsx),返回 (segment_hashes, boq_baseline_hashes)。

    这是 sync 函数,被 ``_extract_tender_archive`` 用 asyncio.to_thread 调用。

    Returns:
        (seg_hashes_unique_list, boq_hashes_unique_list);两个集合在 zip 内合并去重。

    Raises:
        Exception: 解析失败上抛,调用方捕获写 parse_status='failed'。
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"tender file not found: {file_path}")

    seg_hashes_seen: set[str] = set()
    seg_hashes_list: list[str] = []
    boq_hashes_seen: set[str] = set()
    boq_hashes_list: list[str] = []

    def _add_segments(segments: list[str]) -> None:
        for text in segments:
            h = _segment_hash(text)
            if h is None:
                continue
            if h in seg_hashes_seen:
                continue
            seg_hashes_seen.add(h)
            seg_hashes_list.append(h)

    def _add_boq(hashes: list[str]) -> None:
        for h in hashes:
            if h in boq_hashes_seen:
                continue
            boq_hashes_seen.add(h)
            boq_hashes_list.append(h)

    suffix = path.suffix.lower()
    if suffix == ".docx":
        _add_segments(_extract_docx_segments(path))
    elif suffix == ".xlsx":
        seg, boq = _extract_xlsx_segments_and_boq(path)
        _add_segments(seg)
        _add_boq(boq)
    elif suffix == ".zip":
        with tempfile.TemporaryDirectory(prefix="tender_extract_") as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(path, "r") as zf:
                # 安全:只解压 docx/xlsx,跳过其他;不递归 zip(tender 不嵌套)
                for name in zf.namelist():
                    inner_suffix = Path(name).suffix.lower()
                    if inner_suffix not in {".docx", ".xlsx"}:
                        continue
                    # 防 zip-slip
                    safe_name = Path(name).name
                    if not safe_name:
                        continue
                    extract_to = tmp_path / safe_name
                    with zf.open(name) as src, extract_to.open("wb") as dst:
                        dst.write(src.read())
                    if inner_suffix == ".docx":
                        try:
                            _add_segments(_extract_docx_segments(extract_to))
                        except Exception as exc:
                            logger.warning(
                                "tender zip member %s docx parse failed: %s",
                                name,
                                exc,
                            )
                    else:  # .xlsx
                        try:
                            seg, boq = _extract_xlsx_segments_and_boq(extract_to)
                            _add_segments(seg)
                            _add_boq(boq)
                        except Exception as exc:
                            logger.warning(
                                "tender zip member %s xlsx parse failed: %s",
                                name,
                                exc,
                            )
    else:
        raise ValueError(
            f"unsupported tender file extension: {suffix} (expected .docx/.xlsx/.zip)"
        )

    logger.info(
        "tender %s parsed: %d segments, %d BOQ hashes",
        file_path,
        len(seg_hashes_list),
        len(boq_hashes_list),
    )
    return seg_hashes_list, boq_hashes_list


__all__ = ["parse_tender_archive"]
