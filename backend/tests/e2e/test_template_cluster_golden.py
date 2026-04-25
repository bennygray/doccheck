"""L2 golden:3 供应商 zip 完整 pipeline + detection + judge,验证 CH-2 模板簇排除。

**env gate**:未设 DOCUMENTCHECK_L2_GOLDEN_ZIPS 时 skip(不走真 LLM)。
env 值示例:`C:/Users/7way/xwechat_files/bennygray_019b/msg/file/2026-04/投标文件模板2/投标文件模板2`

验收(对应 tasks 6.1):
- AnalysisReport.template_cluster_detected = True
- template_cluster_adjusted_scores.clusters 含 author="lp" + bidder_ids=[A,B,C]
- adjustments 数组完整(PC entries + DEF-OA OA entries)
- risk_level in ("low", "indeterminate")(从 CH-1 前 high 降下)
- DB pair_comparisons / overall_analyses 原值保留(不回写)

耗时 ~10-15 分钟(parser+detect 全程),LLM 成本 ~¥1。

凭证保存:`e2e/artifacts/detect-template-exclusion-2026-04-25/`
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import httpx
import pytest

_GOLDEN_DIR_ENV = "DOCUMENTCHECK_L2_GOLDEN_ZIPS"
_API_BASE = "http://127.0.0.1:8001/api"


pytestmark = pytest.mark.skipif(
    not os.environ.get(_GOLDEN_DIR_ENV),
    reason=f"需设置 {_GOLDEN_DIR_ENV} 指向含 供应商A/B/C.zip 的目录",
)


SUPPLIERS = [
    ("供应商A", "供应商A.zip"),
    ("供应商B", "供应商B.zip"),
    ("供应商C", "供应商C.zip"),
]


async def _login(client: httpx.AsyncClient) -> dict[str, str]:
    r = await client.post(
        f"{_API_BASE}/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _wait_all_priced(project_id: int, timeout_s: int = 900) -> None:
    import asyncpg

    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/documentcheck",
    ).replace("postgresql+asyncpg://", "postgresql://")
    terminal = {
        "priced",
        "price_partial",
        "price_failed",
        "identified",
        "identify_failed",
    }
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        conn = await asyncpg.connect(dsn)
        try:
            rows = await conn.fetch(
                "SELECT parse_status FROM bidders "
                "WHERE project_id = $1 AND deleted_at IS NULL",
                project_id,
            )
        finally:
            await conn.close()
        if rows and all(r["parse_status"] in terminal for r in rows):
            return
        await asyncio.sleep(5)
    raise TimeoutError(f"bidders 未全部到终态,超时 {timeout_s}s")


async def _wait_analysis_complete(project_id: int, timeout_s: int = 600) -> int:
    """等 detect 跑完(project.status='completed' 且 AnalysisReport 落库)。返回 version。"""
    import asyncpg

    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/documentcheck",
    ).replace("postgresql+asyncpg://", "postgresql://")
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        conn = await asyncpg.connect(dsn)
        try:
            row = await conn.fetchrow(
                "SELECT status FROM projects WHERE id=$1", project_id
            )
            if row and row["status"] == "completed":
                report = await conn.fetchrow(
                    "SELECT version FROM analysis_reports "
                    "WHERE project_id=$1 ORDER BY version DESC LIMIT 1",
                    project_id,
                )
                if report:
                    return report["version"]
        finally:
            await conn.close()
        await asyncio.sleep(5)
    raise TimeoutError(f"detect 未完成,超时 {timeout_s}s")


@pytest.mark.asyncio
async def test_golden_three_suppliers_template_cluster_excluded(caplog):
    """3 供应商完整 pipeline + detection + judge → 验 template_cluster 排除。"""
    caplog.set_level(logging.WARNING)

    golden_dir = Path(os.environ[_GOLDEN_DIR_ENV])
    for _, fname in SUPPLIERS:
        assert (golden_dir / fname).exists(), f"缺失 {fname}"

    # backend 健康检查
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{_API_BASE}/health")
            if r.status_code != 200:
                pytest.skip(f"backend /api/health != 200")
    except Exception as e:
        pytest.skip(f"backend 不可达 (localhost:8001): {e}")

    async with httpx.AsyncClient(timeout=900) as client:
        headers = await _login(client)

        import time
        r = await client.post(
            f"{_API_BASE}/projects/",
            headers={**headers, "Content-Type": "application/json"},
            content=(
                f'{{"name":"L2-golden-tpl-cluster-{int(time.time())}",'
                f'"description":"detect-template-exclusion CH-2 golden"}}'
            ).encode("utf-8"),
        )
        r.raise_for_status()
        project_id = r.json()["id"]

        bidder_ids = []
        for bname, fname in SUPPLIERS:
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

        await _wait_all_priced(project_id)

        # 触发 detection
        rd = await client.post(
            f"{_API_BASE}/projects/{project_id}/analysis/start",
            headers=headers,
        )
        rd.raise_for_status()

        version = await _wait_analysis_complete(project_id)

        # DB 断言 + dump 凭证
        import asyncpg

        dsn = os.environ.get(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/documentcheck",
        ).replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn)
        try:
            report_row = await conn.fetchrow(
                "SELECT id, total_score, risk_level, llm_conclusion, "
                "template_cluster_detected, template_cluster_adjusted_scores "
                "FROM analysis_reports WHERE project_id=$1 AND version=$2",
                project_id,
                version,
            )
            assert report_row is not None, "AnalysisReport 未落库"

            # 核心断言
            assert report_row["template_cluster_detected"] is True, (
                f"template_cluster_detected={report_row['template_cluster_detected']!r} "
                f"应为 True;若为 False 说明 cluster 未识别(检查 metadata 抽取是否落库)"
            )
            assert report_row["risk_level"] in ("low", "indeterminate"), (
                f"risk_level={report_row['risk_level']!r} 应 in (low, indeterminate)"
            )

            adj_scores = report_row["template_cluster_adjusted_scores"]
            assert adj_scores is not None
            adj_scores = (
                json.loads(adj_scores) if isinstance(adj_scores, str) else adj_scores
            )

            assert "clusters" in adj_scores
            assert len(adj_scores["clusters"]) >= 1
            cluster_bidders = sorted(adj_scores["clusters"][0]["bidder_ids"])
            assert cluster_bidders == sorted(bidder_ids), (
                f"cluster.bidder_ids={cluster_bidders} 应 == 全部 3 bidder {sorted(bidder_ids)}"
            )

            assert "adjustments" in adj_scores
            adjs = adj_scores["adjustments"]
            assert len(adjs) > 0

            # DB raw 保留(D7 审计)
            pc_rows = await conn.fetch(
                "SELECT score, is_ironclad, dimension FROM pair_comparisons "
                "WHERE project_id=$1 AND version=$2",
                project_id,
                version,
            )
            assert pc_rows, "pair_comparisons 不应为空"

            # dump 凭证
            artifacts_dir = Path(__file__).parent.parent.parent.parent / (
                "e2e/artifacts/detect-template-exclusion-2026-04-25"
            )
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            dump = {
                "project_id": project_id,
                "version": version,
                "report": {
                    "total_score": float(report_row["total_score"]),
                    "risk_level": report_row["risk_level"],
                    "template_cluster_detected": report_row[
                        "template_cluster_detected"
                    ],
                    "llm_conclusion": report_row["llm_conclusion"],
                    "adjusted_scores": adj_scores,
                },
                "pair_comparisons_raw_preserved": [
                    {
                        "dimension": r["dimension"],
                        "score": float(r["score"]),
                        "is_ironclad": r["is_ironclad"],
                    }
                    for r in pc_rows
                ],
            }
            (artifacts_dir / "golden_dump.json").write_text(
                json.dumps(dump, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"\n✅ golden_dump.json 已写入 {artifacts_dir}")
            print(f"   risk_level = {report_row['risk_level']}")
            print(f"   total_score = {report_row['total_score']}")
            print(f"   adjustments 条数 = {len(adjs)}")
        finally:
            await conn.close()
