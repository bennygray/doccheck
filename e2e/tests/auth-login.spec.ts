/**
 * L3: 登录 / 强制改密完整 UI 流程 (C2 auth, US-1.1 + US-1.4)
 *
 * 依赖 globalSetup 每次运行前把 admin 复位到 admin123 + must_change_password=true。
 */
import { execSync } from "node:child_process";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { ADMIN_E2E_PWD } from "../fixtures/auth-helper";

// M1 演示截图保存目录(manual 交付凭证)
const DEMO_DIR = path.resolve(__dirname, "..", "artifacts", "m1-demo-2026-04-14");

// 本 spec 会把 admin 密码从 admin123 改到 E2E 专用值,跑完必须复位,
// 让后续 spec(smoke-home / auth-route-guard)的 loginAdmin helper 仍可用。
test.afterAll(() => {
  const backend = path.resolve(__dirname, "..", "..", "backend");
  execSync("uv run python -m scripts.reset_admin_for_e2e", {
    cwd: backend,
    stdio: "inherit",
  });
});

test.describe("登录与强制改密 UI 流程", () => {
  test("未登录访问 / → 重定向 /login,填 admin 凭证后走完强制改密 → 进入 /projects", async ({
    page,
  }) => {
    // 1. 未登录访问 / → /login (M1 凭证 01)
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.locator("h1")).toContainText("围标检测系统");
    await page.getByTestId("login-username").fill("admin");
    await page.getByTestId("login-password").fill("admin123");
    await page.screenshot({ path: path.join(DEMO_DIR, "01-login.png") });
    await page.getByTestId("login-submit").click();

    // 2. must_change_password=true → 被强制跳 /change-password (M1 凭证 02)
    await expect(page).toHaveURL(/\/change-password$/);
    await expect(page.getByTestId("force-notice")).toBeVisible();
    await page.getByTestId("old-password").fill("admin123");
    await page.getByTestId("new-password").fill(ADMIN_E2E_PWD);
    await page.getByTestId("confirm-password").fill(ADMIN_E2E_PWD);
    await page.screenshot({ path: path.join(DEMO_DIR, "02-change-password.png") });
    await page.getByTestId("change-password-submit").click();

    // 3. 改密后跳回登录页,用新密码登录
    await expect(page).toHaveURL(/\/login$/);
    await page.getByTestId("login-username").fill("admin");
    await page.getByTestId("login-password").fill(ADMIN_E2E_PWD);
    await page.getByTestId("login-submit").click();

    // 4. 进入 /projects (M1 凭证 03)
    await expect(page).toHaveURL(/\/projects$/);
    await expect(page.getByTestId("welcome-user")).toContainText("admin");
    await page.screenshot({ path: path.join(DEMO_DIR, "03-projects.png") });

    // 5. 点登出 → 回 /login (M1 凭证 04)
    await page.getByTestId("logout-btn").click();
    await expect(page).toHaveURL(/\/login$/);
    await page.screenshot({ path: path.join(DEMO_DIR, "04-after-logout.png") });
  });

  test("错误密码 → 留在登录页并显示错误", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("login-username").fill("admin");
    await page.getByTestId("login-password").fill("totally-wrong");
    await page.getByTestId("login-submit").click();
    await expect(page.getByTestId("login-error")).toContainText(
      "用户名或密码错误",
    );
    await expect(page).toHaveURL(/\/login$/);
  });
});
