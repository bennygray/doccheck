import { expect, test } from "@playwright/test";
import { loginAdmin } from "../fixtures/auth-helper";

test.describe("冒烟:登录后首页 + /api/health 代理", () => {
  test("登录后 /projects 渲染成功", async ({ page }) => {
    await loginAdmin(page);
    await page.goto("/projects");
    // C3 起 /projects 的 h1 是 ProjectListPage 的"项目列表"
    await expect(page.locator("h1")).toContainText("项目列表");
    await expect(page.getByTestId("welcome-user")).toContainText("admin");
  });

  test("/api/health 通过前端代理可达且返回 200", async ({ request }) => {
    const resp = await request.get("/api/health");
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body).toHaveProperty("status");
    expect(["ok", "degraded"]).toContain(body.status);
  });
});
