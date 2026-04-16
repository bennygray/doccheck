/**
 * L3 管理后台验收: 用户管理 + 规则配置
 *
 * 覆盖 C17 admin-users 功能的 UI 级 E2E。
 */
import { test, expect } from "@playwright/test";
import { loginAdmin } from "../fixtures/auth-helper";

const TEST_USERNAME = `e2e_user_${Date.now()}`;

test.describe.serial("管理后台: 用户 + 规则配置", () => {
  test("用户管理页面 — 列表 + 创建 + 禁用", async ({ page }) => {
    await loginAdmin(page);
    await page.goto("/admin/users");

    // 验证页面渲染
    await expect(page.getByRole("heading")).toContainText("用户管理");
    await expect(page.getByTestId("users-table")).toBeVisible({ timeout: 10_000 });

    // 至少有 admin 用户行
    const adminRow = page.locator("[data-testid^='user-row-']").first();
    await expect(adminRow).toBeVisible();
    await expect(adminRow).toContainText("admin");

    // 创建新用户
    await page.getByTestId("create-user-btn").click();
    await page.getByTestId("create-user-form").waitFor({ state: "visible" });
    await page.getByTestId("input-username").fill(TEST_USERNAME);
    await page.getByTestId("input-password").fill("TestUser123");
    await page.getByTestId("input-role").selectOption("reviewer");

    await page.getByRole("button", { name: "确认创建" }).click();

    // 验证新用户出现在表格
    await expect(page.getByText(TEST_USERNAME)).toBeVisible({ timeout: 10_000 });

    // 找到新用户的行，点击禁用
    const newUserRow = page.locator(`[data-testid^='user-row-']`, {
      hasText: TEST_USERNAME,
    });
    const toggleBtn = newUserRow.locator("[data-testid^='toggle-active-']");
    await expect(toggleBtn).toContainText("禁用");
    await toggleBtn.click();

    // 验证状态变化
    await expect(toggleBtn).toContainText("启用", { timeout: 5_000 });
  });

  test("规则配置页面 — 查看 + 修改 + 恢复默认", async ({ page }) => {
    await loginAdmin(page);
    await page.goto("/admin/rules");

    // 验证页面渲染
    await expect(page.getByRole("heading", { name: "规则配置" })).toBeVisible();
    await expect(page.getByTestId("dimensions-section")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("global-section")).toBeVisible();

    // 验证至少有维度配置 fieldset
    const dimFieldsets = page.locator("[data-testid^='dim-']").first();
    await expect(dimFieldsets).toBeVisible();

    // 修改一个维度的 weight（取 text_similarity）
    const weightInput = page.getByTestId("dim-text_similarity-weight");
    await expect(weightInput).toBeVisible();
    const originalWeight = await weightInput.inputValue();

    await weightInput.fill("25");

    // 保存
    await page.getByTestId("save-btn").click();
    await expect(page.getByTestId("success-msg")).toBeVisible({ timeout: 10_000 });

    // 验证保存后值保持
    await page.reload();
    await expect(page.getByTestId("dim-text_similarity-weight")).toHaveValue("25", {
      timeout: 10_000,
    });

    // 恢复默认
    // window.confirm 自动接受
    page.on("dialog", (dialog) => dialog.accept());
    await page.getByTestId("restore-btn").click();
    await expect(page.getByTestId("success-msg")).toBeVisible({ timeout: 10_000 });

    // 验证 weight 恢复到默认值（不一定等于 originalWeight，但不是 25）
    await page.reload();
    const restoredWeight = await page.getByTestId("dim-text_similarity-weight").inputValue();
    // 默认权重通常是 10 或 15，不会是我们刚设的 25
    expect(restoredWeight).not.toBe("25");
  });

  test("非 admin 角色无法访问管理后台", async ({ page }) => {
    await loginAdmin(page);

    // 先创建一个 reviewer 并用其登录（通过 API）
    const token = (await page.evaluate(() =>
      window.localStorage.getItem("auth:token"),
    )) as string;

    const reviewerName = `reviewer_${Date.now()}`;
    const res = await page.request.post("/api/admin/users", {
      headers: { Authorization: `Bearer ${token}` },
      data: { username: reviewerName, password: "Reviewer123", role: "reviewer" },
    });
    expect(res.ok()).toBeTruthy();

    // 以 reviewer 身份登录
    const loginRes = await page.request.post("/api/auth/login", {
      data: { username: reviewerName, password: "Reviewer123" },
    });
    expect(loginRes.ok()).toBeTruthy();
    const loginBody = await loginRes.json();

    // 改密（must_change_password=true）
    const changePwdRes = await page.request.post("/api/auth/change-password", {
      headers: { Authorization: `Bearer ${loginBody.access_token}` },
      data: { old_password: "Reviewer123", new_password: "Reviewer123!" },
    });
    expect(changePwdRes.ok()).toBeTruthy();

    // 重新登录获取新 token
    const reloginRes = await page.request.post("/api/auth/login", {
      data: { username: reviewerName, password: "Reviewer123!" },
    });
    const reloginBody = await reloginRes.json();

    // 设置 reviewer 的 localStorage
    await page.goto("/login");
    await page.evaluate(
      ({ t, u }) => {
        window.localStorage.setItem("auth:token", t);
        window.localStorage.setItem("auth:user", JSON.stringify(u));
      },
      { t: reloginBody.access_token, u: reloginBody.user },
    );

    // 尝试访问 admin 页面
    await page.goto("/admin/users");

    // 应被重定向到 /projects 或显示无权限
    await page.waitForURL(/\/(projects|login)/, { timeout: 10_000 });
  });
});
