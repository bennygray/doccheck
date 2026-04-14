/**
 * L3: C4 上传主线 (US-3.1 ~ US-3.4)
 *
 * 主线:登录 → 建项目 → 添加投标人(名 + ZIP)→ 轮询等 parse_status=extracted
 *      → 刷新文件树看到 docx/xlsx → 删除投标人 → 列表更新
 *
 * 注意:依赖 backend extract 协程实际跑(不能 INFRA_DISABLE_EXTRACT=1)。
 */
import { expect, test } from "@playwright/test";
import { loginAdmin } from "../fixtures/auth-helper";
import { createNormalZip } from "../fixtures/archive-fixtures";

const PROJECT_NAME = `C4_Upload_${Date.now()}`;

test.describe("C4 上传主线", () => {
  test.beforeEach(async ({ page }) => {
    page.on("dialog", async (dialog) => {
      await dialog.accept();
    });
  });

  test("登录 → 建项目 → 添加投标人(带 ZIP)→ 轮询解析 → 删除", async ({
    page,
  }) => {
    await loginAdmin(page);

    // 1. 建项目
    await page.goto("/projects/new");
    await page.getByTestId("create-name").fill(PROJECT_NAME);
    await page.getByTestId("create-max-price").fill("100");
    await page.getByTestId("create-submit").click();
    await expect(page).toHaveURL(/\/projects\/\d+$/);
    const projectId = page.url().match(/\/projects\/(\d+)$/)![1];

    // 2. 添加投标人,带 ZIP
    await page.getByTestId("open-add-bidder").click();
    await expect(page.getByTestId("add-bidder-dialog")).toBeVisible();
    await page.getByTestId("bidder-name-input").fill("A 公司");

    const zipPath = createNormalZip();
    await page.getByTestId("bidder-file-input").setInputFiles(zipPath);
    await page.getByTestId("bidder-submit").click();

    // 3. 列表里出现 A 公司,轮询直到 parse_status=extracted
    const card = page.locator('[data-testid^="bidder-card-"]').first();
    await expect(card).toBeVisible();
    const bidderId = (await card.getAttribute("data-testid"))!.replace(
      "bidder-card-",
      "",
    );

    await expect(page.getByTestId(`bidder-status-${bidderId}`)).toContainText(
      /extracted|partial/,
      { timeout: 30_000 },
    );

    // 4. 刷新文件树看到 docx/xlsx
    await page.getByTestId(`bidder-refresh-${bidderId}`).click();
    await expect(page.getByText("📄").first()).toBeVisible();
    await expect(page.getByText("contract.docx")).toBeVisible();

    // 5. 删除投标人(window.confirm 自动接受)
    await page.getByTestId(`bidder-delete-${bidderId}`).click();
    await expect(
      page.getByTestId(`bidder-card-${bidderId}`),
    ).not.toBeVisible({ timeout: 5000 });
  });
});
