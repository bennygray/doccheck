/**
 * L3: 路由守卫 (C2 auth, US-1.3)
 */
import { expect, test } from "@playwright/test";
import { clearAuth, loginAdmin } from "../fixtures/auth-helper";

test.describe("路由守卫", () => {
  test("未登录访问 /projects → 重定向 /login", async ({ page }) => {
    await clearAuth(page);
    await page.goto("/projects");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("登录后访问 /demo/sse(C1 遗留路径)正常进入", async ({ page }) => {
    await loginAdmin(page);
    await page.goto("/demo/sse", { waitUntil: "domcontentloaded" });
    await expect(page.locator("h1")).toContainText("SSE 心跳演示");
  });

  test("登出后 /projects 再次被拦截", async ({ page }) => {
    await loginAdmin(page);
    await page.goto("/projects");
    await expect(page.getByTestId("welcome-user")).toContainText("admin");

    // 点击登出按钮
    await page.getByTestId("logout-btn").click();

    // 已跳回 /login
    await expect(page).toHaveURL(/\/login$/);

    // 手动再次访问 /projects 仍被拦截
    await page.goto("/projects");
    await expect(page).toHaveURL(/\/login$/);
  });
});
