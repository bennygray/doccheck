"""Manual evidence screenshots for fix-bug-triple-and-direction-high (commit 47f731f).

Login UI, navigate to project + reports, capture 3 evidence screenshots:
- tag-sync-bug1.png: project detail page right after detection completes (status=已完成 without nav)
- report-page-bug3.png: report v=1 维度明细 showing price_overshoot 铁证
- report-page-bug2.png: report v=2 维度明细 showing price_total_match 铁证
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BACKEND = "http://localhost:8001"
FRONTEND = "http://localhost:5173"
USERNAME = "admin"
PASSWORD = "Admin12345"

OUT = Path(__file__).resolve().parent

PID = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PID", "2931"))


def login_token() -> str:
    r = requests.post(
        f"{BACKEND}/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def main() -> None:
    token = login_token()
    user = {
        "id": 3535,
        "username": USERNAME,
        "role": "admin",
        "is_active": True,
        "must_change_password": False,
    }

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1600, "height": 900})
        page = ctx.new_page()

        # Inject auth before any navigation
        page.add_init_script(
            f"""window.localStorage.setItem('auth:token', {token!r});
window.localStorage.setItem('auth:user', '{__import__('json').dumps(user)}');"""
        )

        # 1) Bug 1: project detail page (status=已完成 after detection, no page nav prerequisite)
        page.goto(f"{FRONTEND}/projects/{PID}", wait_until="domcontentloaded")
        page.wait_for_selector("text=已完成", timeout=15000)
        time.sleep(2.5)
        path = OUT / "tag-sync-bug1.png"
        page.screenshot(path=str(path), full_page=False)
        print(f"saved {path}")

        # 2) Bug 3: report v=1 维度明细 (price_overshoot 铁证)
        page.goto(f"{FRONTEND}/reports/{PID}/1/dim", wait_until="domcontentloaded")
        page.wait_for_selector("text=price_overshoot", timeout=10000)
        time.sleep(1.5)
        path = OUT / "report-page-bug3.png"
        page.screenshot(path=str(path), full_page=True)
        print(f"saved {path}")

        # 3) Bug 2: report v=2 维度明细 (price_total_match 铁证)
        page.goto(f"{FRONTEND}/reports/{PID}/2/dim", wait_until="domcontentloaded")
        page.wait_for_selector("text=price_total_match", timeout=10000)
        time.sleep(1.5)
        path = OUT / "report-page-bug2.png"
        page.screenshot(path=str(path), full_page=True)
        print(f"saved {path}")

        b.close()


if __name__ == "__main__":
    main()
