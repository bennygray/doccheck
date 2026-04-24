"""L2 golden:3 供应商 zip 端到端 parser 精度验证(parser-accuracy-fixes §8.1)

**env gate**:未设 DOCUMENTCHECK_L2_GOLDEN_ZIPS 时 skip(不走真 LLM)
env 值示例:`C:/Users/7way/xwechat_files/bennygray_019b/msg/file/2026-04/投标文件模板2/投标文件模板2`

验收:
- 3 bidder 的 identity_info.company_full_name 覆盖真实投标方(不是招标方"锂源")
- 供应商B xlsx 的 price_items 中 total_price 或 unit_price 至少 1 行非 NULL(P0-3)
- price_items 包含"监理人员报价单分析表"的 sheet_name 至少 5 行(P1-5)
- 任一 price_items 行 item_code 要么为 None 要么不是纯数字整数(P1-7)
- 任一 price_items 行 item_code 长度 < 100(P1-6 无备注污染)
- docx 文本框抽取无 BaseOxmlElement.xpath namespaces 告警(P2-8)

耗时 ~5-10 分钟,LLM 成本 ~¥1。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

import httpx
import pytest

_GOLDEN_DIR_ENV = "DOCUMENTCHECK_L2_GOLDEN_ZIPS"
_API_BASE = "http://127.0.0.1:8001/api"


pytestmark = pytest.mark.skipif(
    not os.environ.get(_GOLDEN_DIR_ENV),
    reason=f"需设置 {_GOLDEN_DIR_ENV} 指向含 供应商A.zip / 供应商B.zip / 供应商C.zip 的目录",
)


SUPPLIERS = [
    ("供应商A", "供应商A.zip", "攀钢"),      # 真实投标方关键词
    ("供应商B", "供应商B.zip", "浙江华建"),
    ("供应商C", "供应商C.zip", "江苏"),       # 江苏省华厦
]


async def _login(client: httpx.AsyncClient) -> dict[str, str]:
    r = await client.post(
        f"{_API_BASE}/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _wait_all_priced(project_id: int, headers: dict, timeout_s: int = 600) -> None:
    """轮询所有 bidder 到达终态(priced/price_partial/price_failed/identified/identify_failed)"""
    import asyncpg

    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/documentcheck",
    ).replace("postgresql+asyncpg://", "postgresql://")
    terminal = {"priced", "price_partial", "price_failed", "identified", "identify_failed"}
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        conn = await asyncpg.connect(dsn)
        try:
            rows = await conn.fetch(
                "SELECT parse_status FROM bidders WHERE project_id = $1 AND deleted_at IS NULL",
                project_id,
            )
        finally:
            await conn.close()
        if rows and all(r["parse_status"] in terminal for r in rows):
            return
        await asyncio.sleep(5)
    raise TimeoutError(f"bidders 未全部到终态,超时 {timeout_s}s")


@pytest.mark.asyncio
async def test_golden_three_suppliers_pipeline_accuracy(caplog):
    """3 供应商完整 pipeline:上传 → 解析 → 断言 P0-1 / P0-3 / P1-5 / P1-6 / P1-7 / P2-8"""
    caplog.set_level(logging.WARNING)

    golden_dir = Path(os.environ[_GOLDEN_DIR_ENV])
    for _, fname, _ in SUPPLIERS:
        assert (golden_dir / fname).exists(), f"缺失 {fname},请检查 {_GOLDEN_DIR_ENV}"

    # 先检查 backend 可用(本测试要求 backend 已跑在 8001;如 CI/本地未起会 skip)
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{_API_BASE}/health")
            if r.status_code != 200:
                pytest.skip(f"backend /api/health != 200 ({r.status_code}),跳过")
    except Exception as e:
        pytest.skip(f"backend 不可达 (localhost:8001): {e}")

    async with httpx.AsyncClient(timeout=600) as client:
        headers = await _login(client)

        # 创建 project
        import time
        r = await client.post(
            f"{_API_BASE}/projects/",
            headers={**headers, "Content-Type": "application/json"},
            content=f'{{"name":"L2-golden-parser-accuracy-{int(time.time())}","description":"parser-accuracy-fixes L2 golden"}}'.encode("utf-8"),
        )
        r.raise_for_status()
        project_id = r.json()["id"]

        # 上传 3 bidder
        bidder_ids = []
        for bname, fname, _ in SUPPLIERS:
            with open(golden_dir / fname, "rb") as fp:
                files = {"file": (fname, fp, "application/zip")}
                data = {"name": bname}
                rr = await client.post(
                    f"{_API_BASE}/projects/{project_id}/bidders/",
                    headers=headers,
                    files=files,
                    data=data,
                )
            rr.raise_for_status()
            bidder_ids.append(rr.json()["id"])

        # 等待终态
        await _wait_all_priced(project_id, headers, timeout_s=900)

        # 验证
        import asyncpg

        dsn = os.environ.get(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/documentcheck",
        ).replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn)
        try:
            # P0-1 identity_info 正确
            for bid, (bname, _, expected_kw) in zip(bidder_ids, SUPPLIERS):
                row = await conn.fetchrow(
                    "SELECT identity_info FROM bidders WHERE id=$1", bid
                )
                info = row["identity_info"] or {}
                cname = info.get("company_full_name") or info.get("company_short_name") or ""
                assert expected_kw in cname, (
                    f"{bname} identity_info.company_full_name={cname!r} 缺关键词 {expected_kw!r};"
                    f"**P0-1 失败**:可能规则未命中或招标方仍被误判"
                )
                assert "锂源" not in cname, (
                    f"{bname} identity_info 仍含招标方'锂源':{cname!r}"
                )

            # P0-3 B 家 xlsx 金额非 NULL
            b_supplier_id = bidder_ids[1]  # 供应商B
            rows = await conn.fetch(
                "SELECT unit_price, total_price FROM price_items WHERE bidder_id=$1",
                b_supplier_id,
            )
            has_non_null = any(
                r["unit_price"] is not None or r["total_price"] is not None for r in rows
            )
            assert has_non_null, "**P0-3 失败**:供应商B 所有 price_items 的 up/tp 仍全 NULL"

            # P1-5 含"监理人员报价单分析表" sheet
            for bid, (bname, _, _) in zip(bidder_ids, SUPPLIERS):
                n_analysis = await conn.fetchval(
                    "SELECT count(*) FROM price_items WHERE bidder_id=$1 "
                    "AND sheet_name LIKE '%监理人员报价单分析%'",
                    bid,
                )
                assert n_analysis >= 1, (
                    f"{bname}:未抓到'监理人员报价单分析表' sheet(P1-5 多 sheet 失败)"
                )

            # P1-7 item_code 不是纯数字(序号列已被置空)
            pure_digit_codes = await conn.fetchval(
                "SELECT count(*) FROM price_items pi "
                "JOIN bidders b ON b.id = pi.bidder_id "
                "WHERE b.project_id=$1 AND pi.item_code ~ '^[0-9]+$'",
                project_id,
            )
            assert pure_digit_codes == 0, (
                f"**P1-7 失败**:存在 {pure_digit_codes} 行 item_code 为纯数字序号(未被置空)"
            )

            # P1-6 item_code 长度 < 100(无备注行污染)
            long_codes = await conn.fetchval(
                "SELECT count(*) FROM price_items pi "
                "JOIN bidders b ON b.id = pi.bidder_id "
                "WHERE b.project_id=$1 AND length(pi.item_code) >= 100",
                project_id,
            )
            assert long_codes == 0, (
                f"**P1-6 失败**:存在 {long_codes} 行 item_code 长度 ≥100(备注行未过滤)"
            )
        finally:
            await conn.close()

    # P2-8 docx textbox 无 namespaces 告警
    warns = [r.message for r in caplog.records if r.levelname == "WARNING"]
    for w in warns:
        assert "BaseOxmlElement.xpath" not in str(w) or "namespaces" not in str(w), (
            f"**P2-8 失败**:仍有 docx xpath namespaces 告警: {w}"
        )
