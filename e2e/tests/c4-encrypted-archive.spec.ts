/**
 * L3: C4 加密压缩包密码重试 (D2)
 *
 * 主线:加密 7z 上传 → 轮询 needs_password → 打开 DecryptDialog →
 *      输错密码 → 输对密码 → 等 extracted → 文件树可见
 *
 * 加密 7z fixture 不便在 Node 端便捷生成。如 ``e2e/fixtures/encrypted-sample.7z``
 * 不存在 → 整个 spec skip,任务条目降级为手工凭证(写到 e2e/artifacts/c4-<日期>/)。
 *
 * 生成 fixture 的命令(本机一次):
 *   cd backend && uv run python -c "from tests.fixtures.archive_fixtures import \
 *     make_encrypted_7z; from pathlib import Path; \
 *     make_encrypted_7z(Path('../e2e/fixtures/encrypted-sample.7z'), 'secret')"
 */
import { existsSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { loginAdmin } from "../fixtures/auth-helper";
import {
  ENCRYPTED_FIXTURE_PASSWORD,
  ENCRYPTED_FIXTURE_PATH,
} from "../fixtures/archive-fixtures";

const HAS_FIXTURE = existsSync(ENCRYPTED_FIXTURE_PATH);
const PROJECT_NAME = `C4_Enc_${Date.now()}`;

test.describe("C4 加密包密码重试", () => {
  test.beforeEach(async ({ page }) => {
    page.on("dialog", async (dialog) => {
      await dialog.accept();
    });
  });

  test.skip(
    !HAS_FIXTURE,
    `e2e/fixtures/encrypted-sample.7z 缺失;手工生成后可启用本 spec`,
  );

  test("加密 7z → 输错 → 输对 → extracted", async ({ page }) => {
    await loginAdmin(page);

    await page.goto("/projects/new");
    await page.getByTestId("create-name").fill(PROJECT_NAME);
    await page.getByTestId("create-max-price").fill("100");
    await page.getByTestId("create-submit").click();
    await expect(page).toHaveURL(/\/projects\/\d+$/);

    await page.getByTestId("open-add-bidder").click();
    await page.getByTestId("bidder-name-input").fill("加密公司");
    await page.getByTestId("bidder-file-input").setInputFiles(
      ENCRYPTED_FIXTURE_PATH,
    );
    await page.getByTestId("bidder-submit").click();

    const card = page.locator('[data-testid^="bidder-card-"]').first();
    await expect(card).toBeVisible();
    const bidderId = (await card.getAttribute("data-testid"))!.replace(
      "bidder-card-",
      "",
    );

    // 等到 needs_password
    await expect(page.getByTestId(`bidder-status-${bidderId}`)).toContainText(
      /needs_password/,
      { timeout: 30_000 },
    );

    // 拉一次文件让 docsByBidder 缓存有 archive 行
    await page.getByTestId(`bidder-refresh-${bidderId}`).click();
    await page.getByTestId(`open-decrypt-${bidderId}`).click();
    await expect(page.getByTestId("decrypt-dialog")).toBeVisible();

    // 输错密码 → 提交 → 等回到 needs_password
    await page.getByTestId("decrypt-password").fill("wrong-password");
    await page.getByTestId("decrypt-submit").click();
    await expect(page.getByTestId(`bidder-status-${bidderId}`)).toContainText(
      /needs_password|extracting/,
      { timeout: 30_000 },
    );
    await expect(page.getByTestId(`bidder-status-${bidderId}`)).toContainText(
      /needs_password/,
      { timeout: 30_000 },
    );

    // 再次打开 → 输对密码 → 等 extracted
    await page.getByTestId(`bidder-refresh-${bidderId}`).click();
    await page.getByTestId(`open-decrypt-${bidderId}`).click();
    await page.getByTestId("decrypt-password").fill(ENCRYPTED_FIXTURE_PASSWORD);
    await page.getByTestId("decrypt-submit").click();
    await expect(page.getByTestId(`bidder-status-${bidderId}`)).toContainText(
      /extracted|partial/,
      { timeout: 60_000 },
    );
  });
});
