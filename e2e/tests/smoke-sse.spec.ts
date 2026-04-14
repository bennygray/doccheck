import { expect, test } from "@playwright/test";

test.describe("C1 冒烟:SSE demo 心跳", () => {
  test.setTimeout(60_000);
  test("/demo/sse 页至少渲染 1 条心跳", async ({ page }) => {
    // SSE 是长连接,永不触发 load 事件,用 domcontentloaded 即可
    await page.goto("/demo/sse", { waitUntil: "domcontentloaded" });
    await expect(page.locator("h1")).toContainText("SSE 心跳演示");

    // 后端 SSE_HEARTBEAT_INTERVAL_S=1 加速(与 playwright webServer 的 env 对齐)
    await expect(page.getByTestId("sse-count")).not.toHaveText("0", {
      timeout: 15_000,
    });

    // 列表至少 1 条
    const items = page.getByTestId("sse-list").locator("li");
    await expect(items).not.toHaveCount(0);
  });
});
