"""C16 compare-view API — 三类对比视图(只读聚合,不写入数据)。

- GET /{pid}/compare/text    — 文本对比(pair 级)
- GET /{pid}/compare/price   — 报价对比(全项目级)
- GET /{pid}/compare/metadata — 元数据对比(全项目级)
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.analysis_report import AnalysisReport
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.document_metadata import DocumentMetadata
from app.models.document_text import DocumentText
from app.models.pair_comparison import PairComparison
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project, get_visible_projects_stmt
from app.models.user import User
from app.schemas.compare import (
    MetaBidderInfo,
    MetaCellValue,
    MetaCompareResponse,
    MetaFieldRow,
    PriceBidderInfo,
    PriceCell,
    PriceCompareResponse,
    PriceRow,
    TextCompareResponse,
    TextMatch,
    TextParagraph,
)

router = APIRouter()

# ── helpers ────────────────────────────────────────────────────────


async def _visible_project(
    session: AsyncSession, user: User, project_id: int
) -> Project:
    stmt = get_visible_projects_stmt(user).where(Project.id == project_id)
    project = (await session.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "项目不存在")
    return project


async def _latest_version(
    session: AsyncSession, project_id: int
) -> int:
    """取最新 AnalysisReport version;无则 404。"""
    stmt = (
        select(func.max(AnalysisReport.version))
        .where(AnalysisReport.project_id == project_id)
    )
    ver = (await session.execute(stmt)).scalar_one_or_none()
    if ver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该项目无检测报告")
    return ver


def _nfkc_key(s: str | None) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).casefold().strip()


# ── Text Compare (US-7.1) ─────────────────────────────────────────


@router.get(
    "/{project_id}/compare/text",
    response_model=TextCompareResponse,
)
async def compare_text(
    project_id: int,
    bidder_a: int = Query(..., description="投标人 A ID"),
    bidder_b: int = Query(..., description="投标人 B ID"),
    doc_role: str | None = Query(default=None, description="文档角色(选填)"),
    version: int | None = Query(default=None, description="报告版本(选填,默认最新)"),
    limit: int = Query(default=5000, ge=1, le=50000, description="段落数上限"),
    offset: int = Query(default=0, ge=0, description="段落偏移"),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TextCompareResponse:
    await _visible_project(session, user, project_id)
    ver = version if version is not None else await _latest_version(session, project_id)

    # 1) 查该 pair 所有 text_similarity PairComparison
    pc_stmt = select(PairComparison).where(
        PairComparison.project_id == project_id,
        PairComparison.version == ver,
        PairComparison.dimension == "text_similarity",
        PairComparison.bidder_a_id.in_([bidder_a, bidder_b]),
        PairComparison.bidder_b_id.in_([bidder_a, bidder_b]),
    )
    pc_rows = (await session.execute(pc_stmt)).scalars().all()

    # 过滤只保留该 pair 的(a_id, b_id 可能反向)
    pair_pcs: list[PairComparison] = [
        pc for pc in pc_rows
        if {pc.bidder_a_id, pc.bidder_b_id} == {bidder_a, bidder_b}
    ]

    # 可用 doc_role 列表
    available_roles: list[str] = []
    for pc in pair_pcs:
        ej = pc.evidence_json or {}
        role = ej.get("doc_role")
        if role and role not in available_roles:
            available_roles.append(role)

    # 2) 选中的 PairComparison
    selected_pc: PairComparison | None = None
    if doc_role:
        for pc in pair_pcs:
            ej = pc.evidence_json or {}
            if ej.get("doc_role") == doc_role:
                selected_pc = pc
                break
    else:
        # 取 score 最高的
        if pair_pcs:
            selected_pc = max(
                pair_pcs,
                key=lambda p: float(p.score) if p.score is not None else 0.0,
            )

    # 确定实际 doc_role
    actual_role = ""
    if selected_pc:
        actual_role = (selected_pc.evidence_json or {}).get("doc_role", "")

    # 3) 从 evidence_json.samples 提取 matches
    # 注:detection 阶段为 TF-IDF 质量把短段合并(segmenter._merge_short_paragraphs,
    # 用 \n 连接),sample 里的 a_idx/b_idx 是合并后索引。前端展示用原文段,索引不对齐
    # → 我们把 a_text/b_text 按 \n 拆回,然后在该 doc 的原文段里精确匹配文本,生成
    # 一对原文段级 TextMatch(一个合并样本可能派生出多个 match)。
    matches: list[TextMatch] = []
    samples_raw: list[dict] = []
    if selected_pc and selected_pc.evidence_json:
        samples_raw = selected_pc.evidence_json.get("samples", []) or []

    # 4) 确定翻转方向(请求 bidder_a 可能对应 PC 的 bidder_b)
    pc_bidder_a = selected_pc.bidder_a_id if selected_pc else bidder_a
    flip = pc_bidder_a != bidder_a

    # 5) 加载双方段落(先加载,后续还原合并 sample 要用)
    doc_id_a = (selected_pc.evidence_json or {}).get("doc_id_a") if selected_pc else None
    doc_id_b = (selected_pc.evidence_json or {}).get("doc_id_b") if selected_pc else None

    if flip:
        doc_id_a, doc_id_b = doc_id_b, doc_id_a

    # 如果没有 evidence 指向具体 doc,按 file_role 查找
    if doc_id_a is None:
        doc_id_a = await _find_doc_id(
            session, bidder_a, actual_role or doc_role
        )
    if doc_id_b is None:
        doc_id_b = await _find_doc_id(
            session, bidder_b, actual_role or doc_role
        )

    left_paragraphs, total_left = await _load_paragraphs(
        session, doc_id_a, limit, offset
    )
    right_paragraphs, total_right = await _load_paragraphs(
        session, doc_id_b, limit, offset
    )

    # 6) 把合并 sample 拆回原文段级 match
    # 构建 text → paragraph_index 的精确查找(原文段字符串唯一时直接命中)
    left_text_map: dict[str, int] = {
        p.text.strip(): p.paragraph_index for p in left_paragraphs
    }
    right_text_map: dict[str, int] = {
        p.text.strip(): p.paragraph_index for p in right_paragraphs
    }

    for s in samples_raw:
        raw_a_text = s.get("a_text") or ""
        raw_b_text = s.get("b_text") or ""
        # detection 侧是用请求的 pc_bidder_a 的视角;如果 flip,这里要换边
        a_text = raw_b_text if flip else raw_a_text
        b_text = raw_a_text if flip else raw_b_text
        # flip 时 a_idx/b_idx 也要互换,保证返给前端的索引和请求的 bidder_a/b 一致
        orig_a_idx = s.get("b_idx" if flip else "a_idx", 0)
        orig_b_idx = s.get("a_idx" if flip else "b_idx", 0)

        def _fallback() -> None:
            matches.append(
                TextMatch(
                    a_idx=orig_a_idx,
                    b_idx=orig_b_idx,
                    sim=s.get("sim", 0.0),
                    label=s.get("label"),
                    a_text=a_text,
                    b_text=b_text,
                )
            )

        # 按 \n 拆分(segmenter._merge_short_paragraphs 用 \n 连接),对两边分别展开
        a_parts = [x.strip() for x in a_text.split("\n") if x.strip()]
        b_parts = [x.strip() for x in b_text.split("\n") if x.strip()]

        # 无法拆分(单段或空文本)或 document_texts 未加载 → 直接用原 idx
        if not a_parts or not b_parts or not left_text_map or not right_text_map:
            _fallback()
            continue

        # 配对策略:按顺序 zip,逐对建立 match(合并时左右通常等长 2:2)
        emitted = 0
        pair_len = min(len(a_parts), len(b_parts))
        for k in range(pair_len):
            a_idx = left_text_map.get(a_parts[k])
            b_idx = right_text_map.get(b_parts[k])
            if a_idx is None or b_idx is None:
                continue
            matches.append(
                TextMatch(
                    a_idx=a_idx,
                    b_idx=b_idx,
                    sim=s.get("sim", 0.0),
                    label=s.get("label"),
                    a_text=a_parts[k],
                    b_text=b_parts[k],
                )
            )
            emitted += 1
        # 一个 split 都没拆出来 → 保底回原合并 idx
        if emitted == 0:
            _fallback()

    has_more = (total_left > offset + limit) or (total_right > offset + limit)

    return TextCompareResponse(
        bidder_a_id=bidder_a,
        bidder_b_id=bidder_b,
        doc_role=actual_role or doc_role or "",
        available_roles=available_roles,
        left_paragraphs=left_paragraphs,
        right_paragraphs=right_paragraphs,
        matches=matches,
        has_more=has_more,
        total_count_left=total_left,
        total_count_right=total_right,
    )


async def _find_doc_id(
    session: AsyncSession, bidder_id: int, file_role: str | None
) -> int | None:
    """按 bidder + file_role 查第一个 BidDocument.id。"""
    stmt = (
        select(BidDocument.id)
        .where(BidDocument.bidder_id == bidder_id)
    )
    if file_role:
        stmt = stmt.where(BidDocument.file_role == file_role)
    stmt = stmt.order_by(BidDocument.id.asc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def _load_paragraphs(
    session: AsyncSession,
    doc_id: int | None,
    limit: int,
    offset: int,
) -> tuple[list[TextParagraph], int]:
    """加载 DocumentText(location='body')段落。返回 (列表, 总数)。"""
    if doc_id is None:
        return [], 0

    count_stmt = (
        select(func.count())
        .select_from(DocumentText)
        .where(
            DocumentText.bid_document_id == doc_id,
            DocumentText.location == "body",
        )
    )
    total = (await session.execute(count_stmt)).scalar_one()

    stmt = (
        select(DocumentText)
        .where(
            DocumentText.bid_document_id == doc_id,
            DocumentText.location == "body",
        )
        .order_by(DocumentText.paragraph_index.asc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    paragraphs = [
        TextParagraph(paragraph_index=r.paragraph_index, text=r.text)
        for r in rows
    ]
    return paragraphs, total


# ── Price Compare (US-7.2) ─────────────────────────────────────────


@router.get(
    "/{project_id}/compare/price",
    response_model=PriceCompareResponse,
)
async def compare_price(
    project_id: int,
    version: int | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PriceCompareResponse:
    await _visible_project(session, user, project_id)
    if version is not None:
        # 验证报告存在
        ar = (
            await session.execute(
                select(AnalysisReport).where(
                    AnalysisReport.project_id == project_id,
                    AnalysisReport.version == version,
                )
            )
        ).scalar_one_or_none()
        if ar is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")

    # 1) 所有 Bidder(非软删)
    bidder_rows = (
        await session.execute(
            select(Bidder)
            .where(Bidder.project_id == project_id, Bidder.deleted_at.is_(None))
            .order_by(Bidder.id.asc())
        )
    ).scalars().all()
    if not bidder_rows:
        return PriceCompareResponse()

    bidder_ids = [b.id for b in bidder_rows]
    bidders_info = [
        PriceBidderInfo(bidder_id=b.id, bidder_name=b.name) for b in bidder_rows
    ]

    # 2) 所有 PriceItem
    pi_rows = (
        await session.execute(
            select(PriceItem)
            .where(PriceItem.bidder_id.in_(bidder_ids))
            .order_by(PriceItem.bidder_id.asc(), PriceItem.row_index.asc())
        )
    ).scalars().all()
    if not pi_rows:
        return PriceCompareResponse(bidders=bidders_info)

    # 3) 对齐:按 item_name NFKC 归一精确匹配(退化路径,简洁够用)
    # key → { bidder_id → PriceItem }
    alignment: dict[str, dict[int, PriceItem]] = defaultdict(dict)
    # 保留原始 item_name + unit(取第一个出现的)
    key_meta: dict[str, tuple[str, str | None]] = {}
    # 保持插入顺序
    key_order: list[str] = []

    for pi in pi_rows:
        key = _nfkc_key(pi.item_name)
        if not key:
            # 无 item_name:用 (sheet_name, row_index) 做 key
            key = f"__pos__{pi.sheet_name}__{pi.row_index}"
        if key not in key_meta:
            key_meta[key] = (pi.item_name or key, pi.unit)
            key_order.append(key)
        alignment[key][pi.bidder_id] = pi

    # 4) 构建矩阵行
    items: list[PriceRow] = []
    for key in key_order:
        name, unit = key_meta[key]
        cells: list[PriceCell] = []
        prices: list[float] = []

        for bid in bidder_ids:
            pi = alignment[key].get(bid)
            up = float(pi.unit_price) if pi and pi.unit_price is not None else None
            tp = float(pi.total_price) if pi and pi.total_price is not None else None
            cells.append(PriceCell(bidder_id=bid, unit_price=up, total_price=tp))
            if up is not None:
                prices.append(up)

        mean = sum(prices) / len(prices) if prices else None

        # 计算偏差
        has_anomaly = False
        for cell in cells:
            if cell.unit_price is not None and mean and mean != 0:
                dev = (cell.unit_price - mean) / mean * 100
                cell.deviation_pct = round(dev, 2)
                if abs(dev) < 1.0:
                    has_anomaly = True

        items.append(
            PriceRow(
                item_name=name,
                unit=unit,
                mean_unit_price=round(mean, 2) if mean is not None else None,
                cells=cells,
                has_anomaly=has_anomaly,
            )
        )

    # 5) 总报价行 — fix-multi-sheet-price-double-count:仅 SUM sheet_role='main' 行
    # 单一真相源:与 aggregate_bidder_totals 共用 sheet_role 过滤逻辑
    # backward compat:老数据缺 sheet_role 字段 → 默认 main(行为同改前)
    rule_rows = (
        await session.execute(
            select(PriceParsingRule).where(PriceParsingRule.project_id == project_id)
        )
    ).scalars().all()
    # main_sheets[(rule_id, sheet_name)] = True  (in set)
    main_sheets: set[tuple[int, str]] = set()
    for rule in rule_rows:
        for cfg in (rule.sheets_config or []):
            sn = cfg.get("sheet_name")
            role = cfg.get("sheet_role", "main")  # 缺字段默认 main(backward compat)
            if sn and role == "main":
                main_sheets.add((rule.id, sn))

    totals: list[PriceCell] = []
    total_prices: list[float] = []
    for bid in bidder_ids:
        bid_total = Decimal(0)
        has_any = False
        for pi in pi_rows:
            if pi.bidder_id != bid or pi.total_price is None:
                continue
            # main sheet 过滤(与 aggregate_bidder_totals 同源)
            if (pi.price_parsing_rule_id, pi.sheet_name) not in main_sheets:
                continue
            bid_total += pi.total_price
            has_any = True
        tp = float(bid_total) if has_any else None
        totals.append(PriceCell(bidder_id=bid, total_price=tp))
        if tp is not None:
            total_prices.append(tp)

    total_mean = sum(total_prices) / len(total_prices) if total_prices else None
    for cell in totals:
        if cell.total_price is not None and total_mean and total_mean != 0:
            cell.deviation_pct = round(
                (cell.total_price - total_mean) / total_mean * 100, 2
            )

    return PriceCompareResponse(bidders=bidders_info, items=items, totals=totals)


# ── Metadata Compare (US-7.3) ─────────────────────────────────────

# 通用值列表(D6)
METADATA_COMMON_VALUES: dict[str, set[str]] = {
    "author": {"administrator", "admin", "user", "author", ""},
    "last_saved_by": {"administrator", "admin", "user", ""},
    "company": {""},
    "app_name": set(),
}

# 固定 8 字段 + 显示名
_META_FIELDS: list[tuple[str, str]] = [
    ("author", "作者"),
    ("last_saved_by", "最后保存者"),
    ("company", "公司名"),
    ("app_name", "创建软件"),
    ("app_version", "软件版本"),
    ("template", "文档模板"),
    ("doc_created_at", "创建时间"),
    ("doc_modified_at", "修改时间"),
]

# 元数据主文档 role 优先级(D5)
_META_ROLE_PRIORITY: tuple[str, ...] = (
    "commercial",
    "technical",
    "bid_letter",
    "company_intro",
    "other",
)


@router.get(
    "/{project_id}/compare/metadata",
    response_model=MetaCompareResponse,
)
async def compare_metadata(
    project_id: int,
    version: int | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MetaCompareResponse:
    await _visible_project(session, user, project_id)

    # 1) 所有 Bidder
    bidder_rows = (
        await session.execute(
            select(Bidder)
            .where(Bidder.project_id == project_id, Bidder.deleted_at.is_(None))
            .order_by(Bidder.id.asc())
        )
    ).scalars().all()
    if not bidder_rows:
        return MetaCompareResponse()

    bidder_ids = [b.id for b in bidder_rows]
    bidders_info = [
        MetaBidderInfo(bidder_id=b.id, bidder_name=b.name) for b in bidder_rows
    ]

    # 2) 每个 Bidder 选主文档的 DocumentMetadata
    # BidDocument → DocumentMetadata 1:1
    doc_rows = (
        await session.execute(
            select(BidDocument)
            .where(
                BidDocument.bidder_id.in_(bidder_ids),
            )
            .order_by(BidDocument.id.asc())
        )
    ).scalars().all()

    # bidder_id → [(role_priority_idx, doc_id)]
    bidder_docs: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for doc in doc_rows:
        role = doc.file_role or ""
        try:
            pri = _META_ROLE_PRIORITY.index(role)
        except ValueError:
            pri = len(_META_ROLE_PRIORITY)
        bidder_docs[doc.bidder_id].append((pri, doc.id))

    # 选优先级最高(idx 最小)、同级 id 最小的
    primary_doc_ids: dict[int, int] = {}  # bidder_id → doc_id
    for bid_id in bidder_ids:
        candidates = bidder_docs.get(bid_id, [])
        if candidates:
            candidates.sort()
            primary_doc_ids[bid_id] = candidates[0][1]

    # 3) 批量读 DocumentMetadata
    meta_doc_ids = list(primary_doc_ids.values())
    meta_rows: dict[int, DocumentMetadata] = {}
    if meta_doc_ids:
        dm_rows = (
            await session.execute(
                select(DocumentMetadata).where(
                    DocumentMetadata.bid_document_id.in_(meta_doc_ids)
                )
            )
        ).scalars().all()
        for dm in dm_rows:
            meta_rows[dm.bid_document_id] = dm

    # 4) 构建矩阵
    # 先收集每字段所有值(用于 color_group + 高频判定)
    bidder_count = len(bidder_ids)
    threshold_80 = bidder_count * 0.8

    fields_result: list[MetaFieldRow] = []
    for field_attr, display_name in _META_FIELDS:
        # 收集每个 bidder 的值
        raw_values: list[str | None] = []
        for bid_id in bidder_ids:
            doc_id = primary_doc_ids.get(bid_id)
            dm = meta_rows.get(doc_id) if doc_id else None
            if dm is None:
                raw_values.append(None)
            else:
                val = getattr(dm, field_attr, None)
                if val is not None and hasattr(val, "isoformat"):
                    val = val.isoformat()
                elif val is not None:
                    val = str(val)
                raw_values.append(val)

        # color_group:相同非空值同组
        color_map: dict[str, int] = {}
        next_color = 0
        for v in raw_values:
            if v is not None and v != "" and v not in color_map:
                color_map[v] = next_color
                next_color += 1

        # 高频值判定:value → count
        value_counts: dict[str, int] = defaultdict(int)
        for v in raw_values:
            if v is not None:
                value_counts[v] += 1

        # 通用值集合
        common_set = METADATA_COMMON_VALUES.get(field_attr, set())

        cells: list[MetaCellValue] = []
        for v in raw_values:
            is_common = False
            if v is None or v == "":
                is_common = True
            elif _nfkc_key(v) in common_set:
                is_common = True
            elif v in value_counts and value_counts[v] >= threshold_80:
                is_common = True

            cg = color_map.get(v) if v is not None and v != "" else None
            cells.append(MetaCellValue(value=v, is_common=is_common, color_group=cg))

        fields_result.append(
            MetaFieldRow(
                field_name=field_attr,
                display_name=display_name,
                values=cells,
            )
        )

    return MetaCompareResponse(bidders=bidders_info, fields=fields_result)


__all__ = ["router"]
