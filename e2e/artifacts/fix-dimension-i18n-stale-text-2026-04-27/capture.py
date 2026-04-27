"""L3 manual evidence for fix-dimension-i18n-stale-text.

Spawns minimal 2-bidder project (供应商A + 供应商C), max_price=1,000,000 to force
price_overshoot ironclad on 供应商C (total 2,024,400). Captures 4 screenshots
proving:
  1. 检测进度面板 "调度 13 个维度" (during detect startup window)
  2. 报告总览雷达描述 "13 个维度的得分雷达"
  3. 维度明细 price_overshoot 行中文 "超过最高限价"
  4. 对比总览 price_overshoot 维度行中文 (price_total_match 不会触发,只有 2 家)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BACKEND = "http://localhost:8001"
FRONTEND = "http://localhost:5173"
USERNAME = "admin"
PASSWORD = "Admin12345"
ZIP_DIR = Path("C:/Users/7way/xwechat_files/bennygray_019b/msg/file/2026-04/投标文件模板2/投标文件模板2")
OUT = Path(__file__).resolve().parent


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    r = requests.post(
        f"{BACKEND}/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=10,
    )
    token = r.json()["access_token"]
    user_id = r.json()["user"]["id"]
    H = {"Authorization": f"Bearer {token}"}
    print(f"login OK user_id={user_id}")

    r = requests.post(
        f"{BACKEND}/api/projects/",
        json={
            "name": "i18n-fix-l3",
            "max_price": 1000000,
            "bid_code": "I18N-L3",
            "description": "L3 evidence for fix-dimension-i18n-stale-text",
        },
        headers=H,
    )
    pid = r.json()["id"]
    print(f"project={pid}")

    for sup in ["供应商A", "供应商C"]:
        zip_path = ZIP_DIR / f"{sup}.zip"
        with open(zip_path, "rb") as f:
            r = requests.post(
                f"{BACKEND}/api/projects/{pid}/bidders/",
                headers=H,
                data={"name": sup},
                files={"file": (f"{sup}.zip", f, "application/zip")},
                timeout=180,
            )
        print(f"  {sup}: bidder_id={r.json()['id']}")

    print("waiting parse → priced ...")
    deadline = time.time() + 240
    while time.time() < deadline:
        items = requests.get(
            f"{BACKEND}/api/projects/{pid}/bidders/", headers=H, timeout=5
        ).json().get("items", [])
        statuses = [b["parse_status"] for b in items]
        if all(s == "priced" for s in statuses) and len(statuses) == 2:
            print(f"  priced: {statuses}")
            break
        if any("failed" in s or "error" in s for s in statuses):
            raise RuntimeError(f"parse failed: {statuses}")
        time.sleep(5)
    else:
        raise RuntimeError("parse timeout")

    user = json.dumps({
        "id": user_id, "username": USERNAME, "role": "admin",
        "is_active": True, "must_change_password": False,
    })

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1600, "height": 900})
        page = ctx.new_page()
        page.add_init_script(
            f"window.localStorage.setItem('auth:token',{token!r}); "
            f"window.localStorage.setItem('auth:user',{user!r});"
        )

        # Start detection via API right before opening page so we can catch the 'starting' UI
        page.goto(f"{FRONTEND}/projects/{pid}", wait_until="domcontentloaded")
        time.sleep(2)
        # Click 启动检测
        page.click("button:has-text('启动检测')", timeout=5000)
        time.sleep(2.5)  # capture starting/early-running UI
        page.screenshot(path=str(OUT / "01-detect-progress-13-agents.png"))
        print(f"  saved 01-detect-progress-13-agents.png")

        # wait for detection complete via API
        deadline = time.time() + 480
        while time.time() < deadline:
            st = requests.get(
                f"{BACKEND}/api/projects/{pid}/analysis/status",
                headers=H, timeout=5,
            ).json()
            ps = st.get("project_status")
            if ps in ("completed", "ready", "failed"):
                print(f"  detection_done status={ps}")
                break
            time.sleep(8)
        else:
            raise RuntimeError("detect timeout")

        # 2. report overview (radar + 13 caption)
        page.goto(f"{FRONTEND}/reports/{pid}/1", wait_until="domcontentloaded")
        page.wait_for_selector("text=13 个维度的得分雷达", timeout=15000)
        time.sleep(2)
        page.screenshot(
            path=str(OUT / "02-report-radar-13.png"), full_page=False
        )
        print(f"  saved 02-report-radar-13.png")

        # 3. dimension detail with price_overshoot 中文
        page.goto(f"{FRONTEND}/reports/{pid}/1/dim", wait_until="domcontentloaded")
        page.wait_for_selector("text=超过最高限价", timeout=15000)
        time.sleep(2)
        page.screenshot(
            path=str(OUT / "03-dim-overshoot-chinese.png"), full_page=True
        )
        print(f"  saved 03-dim-overshoot-chinese.png")

        # 4. compare overview pair list with overshoot 中文
        page.goto(f"{FRONTEND}/reports/{pid}/1/compare", wait_until="domcontentloaded")
        page.wait_for_selector("text=投标人对比", timeout=15000)
        time.sleep(2)
        page.screenshot(
            path=str(OUT / "04-compare-overview.png"), full_page=True
        )
        print(f"  saved 04-compare-overview.png")

        b.close()

    Path(OUT / "_state.json").write_text(json.dumps({"pid": pid}), encoding="utf-8")
    print(f"done — pid={pid} (cleanup later)")


if __name__ == "__main__":
    main()
