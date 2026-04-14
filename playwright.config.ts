import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright L3 UI E2E 配置 - C1 infra-base
 *
 * - baseURL 默认 http://localhost:5173(Vite dev server)
 * - webServer 自动拉起前端;后端需提前跑(或由 docker compose up 提供)
 * - 测试产物落到 e2e/artifacts/,该目录已加入 .gitignore
 */
export default defineConfig({
  testDir: "./e2e/tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  outputDir: "./e2e/artifacts",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // 本地跑时自动起前端;CI/docker 场景可通过 E2E_NO_WEB_SERVER 跳过
  webServer: process.env.E2E_NO_WEB_SERVER
    ? undefined
    : {
        command: "npm --prefix frontend run dev",
        url: "http://localhost:5173",
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
});
