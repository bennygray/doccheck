"""L1:fill_price_from_rule 多 sheet + M1 异常隔离 + M3 非 confirmed 护栏
     + P1-6 备注行过滤 + P1-7 item_code 序号列识别(parser-accuracy-fixes §3.8 + §4 + §5)

用 openpyxl 实写 xlsx 到 tmp_path,DB 用 asyncpg 真测试库(L2 容器 @55432)。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from openpyxl import Workbook
from sqlalchemy import delete, select

from app.db.session import async_session
from app.models.bid_document import BidDocument
from app.models.bidder import Bidder
from app.models.price_item import PriceItem
from app.models.price_parsing_rule import PriceParsingRule
from app.models.project import Project
from app.models.user import User
from app.services.parser.pipeline.fill_price import (
    PRICE_REMARK_SKIP_MIN_LEN,
    _extract_row,
    fill_price_from_rule,
)


_PREFIX = "fp_ms_"


def _make_xlsx(path: Path, sheets: dict[str, list[list]]) -> Path:
    wb = Workbook()
    # 删除默认 sheet
    default = wb.active
    wb.remove(default)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for r in rows:
            ws.append(r)
    wb.save(path)
    return path


_MAPPING = {
    "code_col": "A",
    "name_col": "B",
    "unit_col": "C",
    "qty_col": "D",
    "unit_price_col": "E",
    "total_price_col": "F",
    "skip_cols": [],
}


@pytest_asyncio.fixture
async def seeded():
    """seed user/project/bidder + 1 确认态 rule;yield (bidder_id, rule_id)。清理前后 seed。"""

    async def _purge():
        async with async_session() as s:
            user_ids = (
                await s.execute(
                    select(User.id).where(User.username.like(f"{_PREFIX}%"))
                )
            ).scalars().all()
            if not user_ids:
                return
            project_ids = (
                await s.execute(
                    select(Project.id).where(Project.owner_id.in_(user_ids))
                )
            ).scalars().all()
            bidder_ids = (
                (
                    await s.execute(
                        select(Bidder.id).where(
                            Bidder.project_id.in_(project_ids)
                        )
                    )
                ).scalars().all()
                if project_ids else []
            )
            if bidder_ids:
                await s.execute(
                    delete(PriceItem).where(PriceItem.bidder_id.in_(bidder_ids))
                )
                await s.execute(
                    delete(BidDocument).where(BidDocument.bidder_id.in_(bidder_ids))
                )
                await s.execute(
                    delete(Bidder).where(Bidder.id.in_(bidder_ids))
                )
            if project_ids:
                await s.execute(
                    delete(PriceParsingRule).where(
                        PriceParsingRule.project_id.in_(project_ids)
                    )
                )
                await s.execute(delete(Project).where(Project.id.in_(project_ids)))
            await s.execute(delete(User).where(User.id.in_(user_ids)))
            await s.commit()

    await _purge()
    async with async_session() as s:
        user = User(
            username=f"{_PREFIX}{id(s)}",
            password_hash="x",
            role="reviewer",
            login_fail_count=0,
        )
        s.add(user); await s.flush()
        project = Project(name="P", owner_id=user.id)
        s.add(project); await s.flush()
        bidder = Bidder(
            name="B", project_id=project.id, parse_status="pricing",
        )
        s.add(bidder); await s.flush()
        rule = PriceParsingRule(
            project_id=project.id,
            sheets_config=[],  # test 各自覆盖
            status="confirmed",
            confirmed=True,
            created_by_llm=True,
            sheet_name="Sheet1",  # backward compat 占位
            header_row=1,
            column_mapping={},
        )
        s.add(rule); await s.flush()
        await s.commit()
        yield bidder.id, rule.id
    await _purge()


# ============================================================ §3.8 multi-sheet


@pytest.mark.asyncio
async def test_multi_sheet_all_success(seeded, tmp_path: Path):
    """3 sheets,每 sheet 都有数据 → 全 succeeded,bidder 进 priced"""
    bidder_id, rule_id = seeded
    xlsx = _make_xlsx(
        tmp_path / "p.xlsx",
        {
            "报价表": [
                ["code", "name", "unit", "qty", "up", "tp"],
                [1, "A", "项", 1, 100, 100],
            ],
            "分析表": [
                ["code", "name", "unit", "qty", "up", "tp"],
                [2, "B", "m", 10, 50, 500],
                [3, "C", "m", 20, 60, 1200],
            ],
            "附表": [
                ["code", "name", "unit", "qty", "up", "tp"],
                [4, "D", "kg", 100, 10, 1000],
            ],
        },
    )
    async with async_session() as s:
        rule = await s.get(PriceParsingRule, rule_id)
        rule.sheets_config = [
            {"sheet_name": "报价表", "header_row": 1, "column_mapping": _MAPPING},
            {"sheet_name": "分析表", "header_row": 1, "column_mapping": _MAPPING},
            {"sheet_name": "附表", "header_row": 1, "column_mapping": _MAPPING},
        ]
        await s.commit()

    async with async_session() as s:
        rule = await s.get(PriceParsingRule, rule_id)
        result = await fill_price_from_rule(s, bidder_id, rule, xlsx)
    assert result.items_count == 4  # 1 + 2 + 1
    assert len(result.succeeded_sheets) == 3
    assert result.partial_failed_sheets == []


@pytest.mark.asyncio
async def test_multi_sheet_missing_sheet_is_partial(seeded, tmp_path: Path):
    """rule 要 2 sheet,xlsx 只有 1 → 另 1 记 partial_failed"""
    bidder_id, rule_id = seeded
    xlsx = _make_xlsx(
        tmp_path / "p.xlsx",
        {
            "报价表": [
                ["code", "name", "unit", "qty", "up", "tp"],
                [1, "A", "项", 1, 100, 100],
            ],
        },
    )
    async with async_session() as s:
        rule = await s.get(PriceParsingRule, rule_id)
        rule.sheets_config = [
            {"sheet_name": "报价表", "header_row": 1, "column_mapping": _MAPPING},
            {"sheet_name": "缺失表", "header_row": 1, "column_mapping": _MAPPING},
        ]
        await s.commit()

    async with async_session() as s:
        rule = await s.get(PriceParsingRule, rule_id)
        result = await fill_price_from_rule(s, bidder_id, rule, xlsx)
    assert result.items_count == 1
    assert result.succeeded_sheets == ["报价表"]
    assert any("缺失表" in x for x in result.partial_failed_sheets)


@pytest.mark.asyncio
async def test_legacy_rule_fallback_single_sheet(seeded, tmp_path: Path):
    """老 rule sheets_config=[] 但 3 老列齐全 → fallback 单 sheet"""
    bidder_id, rule_id = seeded
    xlsx = _make_xlsx(
        tmp_path / "p.xlsx",
        {
            "报价清单": [
                ["code", "name", "unit", "qty", "up", "tp"],
                [1, "A", "项", 1, 100, 100],
            ],
        },
    )
    async with async_session() as s:
        rule = await s.get(PriceParsingRule, rule_id)
        rule.sheets_config = []  # 老数据空
        rule.sheet_name = "报价清单"
        rule.header_row = 1
        rule.column_mapping = _MAPPING
        await s.commit()

    async with async_session() as s:
        rule = await s.get(PriceParsingRule, rule_id)
        result = await fill_price_from_rule(s, bidder_id, rule, xlsx)
    assert result.items_count == 1
    assert result.succeeded_sheets == ["报价清单"]


# ============================================================ M1 单 sheet 异常隔离


@pytest.mark.asyncio
async def test_mid_sheet_exception_rolls_back_partial_items(seeded, tmp_path: Path, monkeypatch):
    """H3 review 修:坏 sheet 中途抛异常,已 add 的 item 必须 SAVEPOINT rollback,不入库。

    Mock:坏表 row[0] OK、row[1] 抛异常 → 断言坏表 0 items 入库;好表不受影响。
    """
    bidder_id, rule_id = seeded
    xlsx = _make_xlsx(
        tmp_path / "p.xlsx",
        {
            "好表": [["code", "name", "unit", "qty", "up", "tp"], [1, "A", "项", 1, 100, 100]],
            "坏表": [
                ["code", "name", "unit", "qty", "up", "tp"],
                [2, "B_row0_ok", "m", 2, 200, 400],  # 第 1 数据行正常
                [3, "B_row1_MID_CRASH", "m", 3, 300, 900],  # 第 2 数据行触发抛异常
            ],
        },
    )
    async with async_session() as s:
        rule = await s.get(PriceParsingRule, rule_id)
        rule.sheets_config = [
            {"sheet_name": "好表", "header_row": 1, "column_mapping": _MAPPING},
            {"sheet_name": "坏表", "header_row": 1, "column_mapping": _MAPPING},
        ]
        await s.commit()

    # monkeypatch:第 2 次在"坏表"调用时抛(mid-sheet)
    from app.services.parser.pipeline import fill_price as fpm
    orig = fpm._extract_row
    call_count_per_sheet: dict[str, int] = {}
    def mid_crash(*, sheet_name, **kw):
        call_count_per_sheet[sheet_name] = call_count_per_sheet.get(sheet_name, 0) + 1
        # 坏表第 2 次(对应 xlsx row_index=2 = row[1] 即第 2 个数据行)抛
        if sheet_name == "坏表" and call_count_per_sheet[sheet_name] == 2:
            raise RuntimeError("mock mid-sheet crash")
        return orig(sheet_name=sheet_name, **kw)
    monkeypatch.setattr(fpm, "_extract_row", mid_crash)

    async with async_session() as s:
        rule = await s.get(PriceParsingRule, rule_id)
        result = await fill_price_from_rule(s, bidder_id, rule, xlsx)

    # 好表 1 条正常入库;坏表中途抛,SAVEPOINT rollback → 0 条入库(非 1 条!)
    assert result.items_count == 1
    assert result.succeeded_sheets == ["好表"]
    assert any("坏表" in x for x in result.partial_failed_sheets)

    # 再次从 DB 验证坏表 0 items 入库(savepoint 确实回滚)
    async with async_session() as s:
        rows = (
            await s.execute(
                select(PriceItem).where(
                    PriceItem.bidder_id == bidder_id,
                    PriceItem.sheet_name == "坏表",
                )
            )
        ).scalars().all()
        assert len(rows) == 0, f"坏表本应 0 items,实际 {len(rows)}(savepoint 未回滚)"


@pytest.mark.asyncio
async def test_single_sheet_exception_isolated(seeded, tmp_path: Path, monkeypatch):
    """M1:某 sheet 的 _extract_row 抛异常(首次调用即抛),其他 sheet 仍处理成功"""
    bidder_id, rule_id = seeded
    xlsx = _make_xlsx(
        tmp_path / "p.xlsx",
        {
            "报价表": [["code", "name", "unit", "qty", "up", "tp"], [1, "A", "项", 1, 100, 100]],
            "坏表": [["code", "name", "unit", "qty", "up", "tp"], [2, "B", "m", 2, 200, 400]],
            "附表": [["code", "name", "unit", "qty", "up", "tp"], [3, "C", "kg", 3, 300, 900]],
        },
    )
    async with async_session() as s:
        rule = await s.get(PriceParsingRule, rule_id)
        rule.sheets_config = [
            {"sheet_name": "报价表", "header_row": 1, "column_mapping": _MAPPING},
            {"sheet_name": "坏表", "header_row": 1, "column_mapping": _MAPPING},
            {"sheet_name": "附表", "header_row": 1, "column_mapping": _MAPPING},
        ]
        await s.commit()

    # monkeypatch:抽到 sheet_name='坏表' 时抛异常
    from app.services.parser.pipeline import fill_price as fpm
    orig = fpm._extract_row
    def broken(*, sheet_name, **kw):
        if sheet_name == "坏表":
            raise RuntimeError("mock sheet error")
        return orig(sheet_name=sheet_name, **kw)
    monkeypatch.setattr(fpm, "_extract_row", broken)

    async with async_session() as s:
        rule = await s.get(PriceParsingRule, rule_id)
        result = await fill_price_from_rule(s, bidder_id, rule, xlsx)
    # 其他 2 sheet 仍正常
    assert result.items_count == 2
    assert set(result.succeeded_sheets) == {"报价表", "附表"}
    # 坏表记 partial_failed
    assert any("坏表" in x for x in result.partial_failed_sheets)


# ============================================================ M3 rule 非 confirmed


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "identifying"])
async def test_rule_not_confirmed_returns_empty(seeded, tmp_path: Path, status):
    """M3:rule.status != confirmed → 返空 FillResult,不走任何 sheet,不写 price_items"""
    bidder_id, rule_id = seeded
    xlsx = _make_xlsx(
        tmp_path / "p.xlsx",
        {"报价表": [["code", "name", "unit", "qty", "up", "tp"], [1, "A", "项", 1, 100, 100]]},
    )
    async with async_session() as s:
        rule = await s.get(PriceParsingRule, rule_id)
        rule.status = status
        rule.sheets_config = [
            {"sheet_name": "报价表", "header_row": 1, "column_mapping": _MAPPING}
        ]
        await s.commit()

    async with async_session() as s:
        rule = await s.get(PriceParsingRule, rule_id)
        result = await fill_price_from_rule(s, bidder_id, rule, xlsx)
    assert result.items_count == 0
    assert result.succeeded_sheets == []
    assert result.partial_failed_sheets == []

    # verify DB 无 price_items
    async with async_session() as s:
        n = (
            await s.execute(
                select(PriceItem).where(PriceItem.bidder_id == bidder_id)
            )
        ).all()
        assert len(n) == 0


# ============================================================ P1-6 remark row filter


class TestRemarkRowFilter:
    """§4.3:扫 text 三字段任一 ≥100 字 + 其他 5 个全空 → skip"""

    def test_remark_long_in_code_col_skipped(self):
        """150 字落 A 列(item_code) + 其他全 None → skip"""
        row = ["备注:" + "x" * 150, None, None, None, None, None]
        assert _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=1,
            row=row, mapping=_MAPPING,
        ) is None

    def test_remark_long_in_name_col_skipped(self):
        """150 字落 B 列(item_name) + 其他全 None → skip(H3 新覆盖)"""
        row = [None, "说明:" + "y" * 150, None, None, None, None]
        assert _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=1,
            row=row, mapping=_MAPPING,
        ) is None

    def test_remark_long_in_unit_col_skipped(self):
        """150 字落 C 列(unit) + 其他全 None → skip(H3 新覆盖)"""
        row = [None, None, "单位说明:" + "z" * 150, None, None, None]
        assert _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=1,
            row=row, mapping=_MAPPING,
        ) is None

    def test_long_name_with_other_fields_not_skipped(self):
        """长 item_name + unit 有值 → 真实业务行,不误伤"""
        row = [None, "描述" * 100, "项", 1, None, None]  # 200 chars in name
        result = _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=1,
            row=row, mapping=_MAPPING,
        )
        assert result is not None
        assert result.item_name and "描述" in result.item_name

    def test_short_name_no_skip(self):
        """<100 字 name → 不触发 skip"""
        row = [None, "短描述", None, None, None, None]
        result = _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=1,
            row=row, mapping=_MAPPING,
        )
        assert result is not None

    def test_remark_sentinel_short_prefix_skipped(self):
        """review M1:item_code 以'备注'开头(短词)+ 数值全空 → skip

        golden 里 B 家 r10 的 "item_code='备注:'"(3 字短)即使 item_name 长,
        也因 item_code 非空导致 H3 长文本规则不触发;此 case 兜住。
        """
        # 备注: 前缀 + 数值全空 → skip
        row = ["备注:", "1. 说明文字...", None, None, None, None]
        assert _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=1,
            row=row, mapping=_MAPPING,
        ) is None

    def test_remark_sentinel_with_numeric_not_skipped(self):
        """'备注' 前缀但数值列有金额 → **不** skip(防真实业务行误伤)"""
        row = ["备注项", "描述", "项", 1, 100, 100]
        result = _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=1,
            row=row, mapping=_MAPPING,
        )
        assert result is not None
        # item_code 保留
        assert result.item_code == "备注项"

    def test_remark_min_len_boundary(self):
        """边界:正好 99 字不 skip;100 字 skip"""
        row_99 = [None, "a" * 99, None, None, None, None]
        assert _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=1,
            row=row_99, mapping=_MAPPING,
        ) is not None  # 99 不触发
        row_100 = [None, "a" * PRICE_REMARK_SKIP_MIN_LEN, None, None, None, None]
        assert _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=1,
            row=row_100, mapping=_MAPPING,
        ) is None  # 100 触发


# ============================================================ P1-7 item_code 序号列


class TestItemCodeOrdinalDetection:
    """§5.2:item_code 纯数字整数 + 其他非空 → 置空"""

    def test_pure_digit_code_with_other_fields_cleared(self):
        """A='1', B 和 F 非空 → item_code 置 None(序号列污染)"""
        row = ["1", "建设工程监理", None, None, 456000, 456000]
        result = _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=1,
            row=row, mapping=_MAPPING,
        )
        assert result is not None
        assert result.item_code is None
        assert result.item_name == "建设工程监理"

    def test_real_code_with_letters_preserved(self):
        """'DT-001' 真编码 → 保留"""
        row = ["DT-001", "XX", "项", 1, 100, 100]
        result = _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=1,
            row=row, mapping=_MAPPING,
        )
        assert result is not None
        assert result.item_code == "DT-001"

    def test_pure_digit_code_alone_kept_as_is(self):
        """L2 review 修:测试名澄清 — A='1' 全空其他字段 → item_code 保留 "1"
        (序号 heuristic 需要 has_other 为真才触发,此 case 不触发)"""
        row = ["1", None, None, None, None, None]
        result = _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=1,
            row=row, mapping=_MAPPING,
        )
        # A=1 非 None,不走"6 字段都空"skip;序号检测 has_other=False → 保留 "1"
        assert result is not None
        assert result.item_code == "1"

    def test_multi_digit_ordinal_cleared(self):
        """A='23' 这种多位数序号也清"""
        row = ["23", "Some name", "项", None, None, None]
        result = _extract_row(
            bidder_id=1, rule_id=1, sheet_name="s", row_index=1,
            row=row, mapping=_MAPPING,
        )
        assert result is not None
        assert result.item_code is None
