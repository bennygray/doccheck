"""C16 compare-view API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Text Compare (US-7.1) ──────────────────────────────────────────


class TextParagraph(BaseModel):
    paragraph_index: int
    text: str


class TextMatch(BaseModel):
    a_idx: int
    b_idx: int
    sim: float
    label: str | None = None
    a_text: str | None = None
    b_text: str | None = None


class TextCompareResponse(BaseModel):
    bidder_a_id: int
    bidder_b_id: int
    doc_role: str
    available_roles: list[str] = Field(default_factory=list)
    left_paragraphs: list[TextParagraph] = Field(default_factory=list)
    right_paragraphs: list[TextParagraph] = Field(default_factory=list)
    matches: list[TextMatch] = Field(default_factory=list)
    has_more: bool = False
    total_count_left: int = 0
    total_count_right: int = 0


# ── Price Compare (US-7.2) ─────────────────────────────────────────


class PriceBidderInfo(BaseModel):
    bidder_id: int
    bidder_name: str


class PriceCell(BaseModel):
    """单个投标人在某报价项上的值。"""

    bidder_id: int
    unit_price: float | None = None
    total_price: float | None = None
    deviation_pct: float | None = None  # (price - mean) / mean * 100


class PriceRow(BaseModel):
    """一行报价项(对齐后)。"""

    item_name: str
    unit: str | None = None
    mean_unit_price: float | None = None
    cells: list[PriceCell] = Field(default_factory=list)
    has_anomaly: bool = False  # 含偏差 <1% 的 cell


class PriceCompareResponse(BaseModel):
    bidders: list[PriceBidderInfo] = Field(default_factory=list)
    items: list[PriceRow] = Field(default_factory=list)
    totals: list[PriceCell] = Field(default_factory=list)


# ── Metadata Compare (US-7.3) ──────────────────────────────────────


class MetaBidderInfo(BaseModel):
    bidder_id: int
    bidder_name: str


class MetaCellValue(BaseModel):
    value: str | None = None
    is_common: bool = False
    color_group: int | None = None  # 同值同组 → 前端着色


class MetaFieldRow(BaseModel):
    field_name: str
    display_name: str
    values: list[MetaCellValue] = Field(default_factory=list)


class MetaCompareResponse(BaseModel):
    bidders: list[MetaBidderInfo] = Field(default_factory=list)
    fields: list[MetaFieldRow] = Field(default_factory=list)
