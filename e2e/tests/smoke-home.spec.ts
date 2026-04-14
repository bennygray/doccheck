import { expect, test } from "@playwright/test";

test.describe("C1 冒烟:首页 + /api/health 代理", () => {
  test("首页渲染成功", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("h1")).toContainText("围标检测系统");
  });

  test("/api/health 通过前端代理可达且返回 200", async ({ page, request }) => {
    const resp = await request.get("/api/health");
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body).toHaveProperty("status");
    // 允许 ok 或 degraded(degraded 也算端点通,只是 DB 可能未起)
    expect(["ok", "degraded"]).toContain(body.status);

    // 同时验证首页能拉到 health 展示
    await page.goto("/");
    await expect(page.getByTestId("health-status")).not.toHaveText("checking...", {
      timeout: 5000,
    });
  });
});
