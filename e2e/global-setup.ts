/**
 * Playwright globalSetup — 每次 E2E 运行前复位 admin 用户状态 (C2 auth)
 *
 * 复位逻辑实现在 backend/scripts/reset_admin_for_e2e.py:
 *   - password → admin123
 *   - must_change_password → true
 *   - login_fail_count → 0, locked_until → null
 *
 * 这样 auth-login.spec.ts 改密测试每次都从"初始 seed 态"开始,smoke 测试
 * 通过 auth-helper 再自行改密到 E2E 专用密码,互不干扰。
 */
import { execSync } from "node:child_process";
import path from "node:path";

export default async function globalSetup() {
  const backend = path.resolve(__dirname, "..", "backend");
  try {
    execSync("uv run python -m scripts.reset_admin_for_e2e", {
      cwd: backend,
      stdio: "inherit",
    });
  } catch (err) {
    console.error(
      "[e2e global-setup] 复位 admin 失败。确认 backend 依赖已 uv sync,PostgreSQL 已启动。",
    );
    throw err;
  }
}
