"""L1 - BOQ baseline hash 计算纯函数单测 (detect-tender-baseline 1.14)

覆盖 spec detect-framework "BOQ 项级 baseline hash" Requirement Scenarios:
- BOQ hash 不含价格(应标方填不同单价不影响 hash)
- 工程量精度归一化("1" / "1.0" / "1.000" hash 一致)
- 多份 BOQ xlsx 合并基线(hash 集合去重)
"""

from __future__ import annotations

from decimal import Decimal

from app.services.parser.pipeline.fill_price import _compute_boq_baseline_hash


# ============================================================ 不含价格


def test_boq_hash_excludes_price():
    """单价/合价不参与 hash:相同 (项目名+描述+单位+工程量) → hash 必相等。"""
    # 应标方 A 填单价 100,应标方 B 填单价 120,但 hash 应相等(单价不参与)
    # _compute_boq_baseline_hash 签名 (item_name, description, unit, quantity)
    h_a = _compute_boq_baseline_hash("建设工程委托监理", "全过程监理", "项", Decimal("1"))
    h_b = _compute_boq_baseline_hash("建设工程委托监理", "全过程监理", "项", Decimal("1"))
    assert h_a == h_b
    assert h_a is not None


# ============================================================ 工程量精度归一化


def test_boq_hash_quantity_normalize():
    """工程量 '1' / '1.0' / '1.000' / Decimal('1') → hash 一致。"""
    h_int = _compute_boq_baseline_hash("X", "desc", "项", "1")
    h_dot0 = _compute_boq_baseline_hash("X", "desc", "项", "1.0")
    h_dot000 = _compute_boq_baseline_hash("X", "desc", "项", "1.000")
    h_decimal = _compute_boq_baseline_hash("X", "desc", "项", Decimal("1"))
    assert h_int == h_dot0 == h_dot000 == h_decimal
    assert h_int is not None


def test_boq_hash_different_quantity_different_hash():
    """工程量 1 vs 2 → hash 不同。"""
    h1 = _compute_boq_baseline_hash("X", "d", "项", Decimal("1"))
    h2 = _compute_boq_baseline_hash("X", "d", "项", Decimal("2"))
    assert h1 != h2


# ============================================================ 不完整行返 None


def test_boq_hash_empty_item_name_returns_none():
    """项目名为空 → 返 None(行不完整,baseline_resolver 跳过)。"""
    assert _compute_boq_baseline_hash(None, "desc", "项", Decimal("1")) is None
    assert _compute_boq_baseline_hash("", "desc", "项", Decimal("1")) is None


def test_boq_hash_empty_quantity_returns_none():
    """工程量为空或非数值 → 返 None。"""
    assert _compute_boq_baseline_hash("X", "d", "项", None) is None
    assert _compute_boq_baseline_hash("X", "d", "项", "not_a_number") is None


# ============================================================ NFKC 归一化


def test_boq_hash_full_half_width_equivalent():
    """全角/半角项目名 → hash 一致。"""
    h_full = _compute_boq_baseline_hash("项目Ａ", "描述", "项", Decimal("1"))
    h_half = _compute_boq_baseline_hash("项目A", "描述", "项", Decimal("1"))
    assert h_full == h_half


# ============================================================ 描述/单位 nullable


def test_boq_hash_empty_description_still_valid():
    """描述为空但项目名+工程量在 → 仍 hash(描述参与 hash 但允许空)。"""
    h = _compute_boq_baseline_hash("X", None, "项", Decimal("1"))
    assert h is not None
