/**
 * L3: 项目 CRUD 主线 (C3 project-mgmt, US-2.1 ~ US-2.4)
 *
 * 主线:登录 → 空态/已有态 → 新建 → 详情 → 列表(搜索/筛选)→ 删除 → 列表再无
 *
 * 为避免前次 run 遗留数据污染,使用带时间戳的唯一项目名。
 * 所有 window.confirm 通过 page.on("dialog") 自动接受。
 */
import { expect, test } from "@playwright/test";
import { loginAdmin } from "../fixtures/auth-helper";

const UNIQUE_NAME = `C3_Playwright_${Date.now()}`;
const UNIQUE_BID = `BID-C3-${Date.now()}`;

test.describe("C3 项目 CRUD 主线", () => {
  test.beforeEach(async ({ page }) => {
    // window.confirm / alert 全部自动接受
    page.on("dialog", async (dialog) => {
      await dialog.accept();
    });
  });

  test("登录 → 新建 → 详情 → 列表 → 搜索 → 筛选 → 删除", async ({ page }) => {
    // 1. 登录并进入 /projects
    await loginAdmin(page);
    await page.goto("/projects");
    await expect(page.getByTestId("welcome-user")).toContainText("admin");

    // 2. 点击 "新建项目" 按钮
    await page.getByTestId("new-project-btn").click();
    await expect(page).toHaveURL(/\/projects\/new$/);

    // 未填 max_price 时显示 US-2.1 提示文案
    await expect(page.getByTestId("no-max-price-hint")).toBeVisible();

    // 3. 填表并提交
    await page.getByTestId("create-name").fill(UNIQUE_NAME);
    await page.getByTestId("create-bid-code").fill(UNIQUE_BID);
    await page.getByTestId("create-max-price").fill("9999.99");
    await page.getByTestId("create-description").fill("C3 L3 test");
    await page.getByTestId("create-submit").click();

    // 4. 跳详情页 → 断言基础字段
    await expect(page).toHaveURL(/\/projects\/\d+$/);
    await expect(page.getByTestId("project-name")).toContainText(UNIQUE_NAME);
    await expect(page.getByTestId("project-status")).toContainText("草稿");
    await expect(page.getByTestId("project-bid-code")).toContainText(UNIQUE_BID);
    await expect(page.getByTestId("project-max-price")).toContainText("9999.99");
    // C4+ 占位区可见
    await expect(page.getByTestId("bidders-placeholder")).toBeVisible();
    await expect(page.getByTestId("files-placeholder")).toBeVisible();
    await expect(page.getByTestId("progress-placeholder")).toBeVisible();

    // 捕获刚创建项目的 id(URL 尾数)
    const urlMatch = page.url().match(/\/projects\/(\d+)$/);
    expect(urlMatch).not.toBeNull();
    const projectId = urlMatch![1];

    // 5. 返回列表页,确认新项目在列表中
    await page.getByTestId("back-to-list").click();
    await expect(page).toHaveURL(/\/projects$/);
    await expect(page.getByTestId(`project-card-${projectId}`)).toBeVisible();

    // 6. 搜索框按项目名匹配
    await page.getByTestId("search-input").fill(UNIQUE_NAME);
    await page.getByTestId("search-submit").click();
    await expect(page.getByTestId(`project-card-${projectId}`)).toBeVisible();
    // 搜索命中就不应再有空态
    await expect(page.getByTestId("empty-state")).not.toBeVisible();

    // 清搜索,再按 status=draft 筛选
    await page.getByTestId("search-input").fill("");
    await page.getByTestId("search-submit").click();
    await page.getByTestId("filter-status").selectOption("draft");
    await expect(page.getByTestId(`project-card-${projectId}`)).toBeVisible();

    // 7. 在列表页点 "删除"(window.confirm 自动接受)
    await page.getByTestId(`project-delete-${projectId}`).click();

    // 等待删除后重新加载
    await expect(
      page.getByTestId(`project-card-${projectId}`),
    ).not.toBeVisible({ timeout: 5000 });

    // 8. 清筛选(否则一直 status=draft)后再搜索,确认彻底消失
    await page.getByTestId("filter-status").selectOption("");
    await page.getByTestId("search-input").fill(UNIQUE_NAME);
    await page.getByTestId("search-submit").click();
    await expect(page.getByTestId("empty-state")).toBeVisible();
  });

  test("未填 name 提交 → 显示错误且停在创建页", async ({ page }) => {
    await loginAdmin(page);
    await page.goto("/projects/new");

    // 用空白名触发 JS 校验(原生 required 只拦 "",空白能过)
    await page.getByTestId("create-name").fill("   ");
    await page.getByTestId("create-submit").click();

    await expect(page.getByTestId("create-error")).toContainText(
      "名称不能为空",
    );
    await expect(page).toHaveURL(/\/projects\/new$/);
  });
});
