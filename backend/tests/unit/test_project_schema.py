"""L1: ProjectCreate schema 校验 (C3 project-mgmt)。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.project import ProjectCreate, ProjectListQuery


class TestProjectCreate:
    def test_minimal_valid(self) -> None:
        p = ProjectCreate(name="测试项目")
        assert p.name == "测试项目"
        assert p.bid_code is None
        assert p.max_price is None
        assert p.description is None

    def test_full_valid(self) -> None:
        p = ProjectCreate(
            name="某高速投标",
            bid_code="BID-2026-001",
            max_price=Decimal("12345678.90"),
            description="说明",
        )
        assert p.bid_code == "BID-2026-001"
        assert p.max_price == Decimal("12345678.90")

    def test_name_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectCreate(name="")

    def test_name_blank_rejected(self) -> None:
        # 纯空白被 strip 后视为空
        with pytest.raises(ValidationError):
            ProjectCreate(name="   ")

    def test_name_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectCreate(name="x" * 101)

    def test_name_stripped(self) -> None:
        p = ProjectCreate(name="  某项目  ")
        assert p.name == "某项目"

    def test_bid_code_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectCreate(name="x", bid_code="b" * 51)

    def test_bid_code_empty_string_normalized_to_none(self) -> None:
        p = ProjectCreate(name="x", bid_code="")
        assert p.bid_code is None

    def test_description_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectCreate(name="x", description="d" * 501)

    def test_description_empty_string_normalized_to_none(self) -> None:
        p = ProjectCreate(name="x", description="")
        assert p.description is None

    def test_max_price_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectCreate(name="x", max_price=Decimal("-1"))

    def test_max_price_three_decimals_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectCreate(name="x", max_price=Decimal("1.234"))

    def test_max_price_zero_allowed(self) -> None:
        p = ProjectCreate(name="x", max_price=Decimal("0"))
        assert p.max_price == Decimal("0")

    def test_max_price_over_18_digits_rejected(self) -> None:
        # 19 位整数超 DECIMAL(18,2) 容量
        with pytest.raises(ValidationError):
            ProjectCreate(name="x", max_price=Decimal("1" * 19))


class TestProjectListQuery:
    def test_defaults(self) -> None:
        q = ProjectListQuery()
        assert q.page == 1
        assert q.size == 12

    def test_page_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectListQuery(page=0)

    def test_size_over_100_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectListQuery(size=101)

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectListQuery(status="bogus")

    def test_invalid_risk_level_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectListQuery(risk_level="extreme")

    def test_empty_search_normalized_to_none(self) -> None:
        q = ProjectListQuery(search="   ")
        assert q.search is None

    def test_valid_full(self) -> None:
        q = ProjectListQuery(
            page=2, size=12, status="draft", risk_level="high", search="abc"
        )
        assert q.status == "draft"
        assert q.risk_level == "high"
        assert q.search == "abc"
