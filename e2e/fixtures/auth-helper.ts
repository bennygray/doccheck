/**
 * E2E auth helper (C2)
 *
 * loginAdmin(page): 幂等的 admin 登录
 *   - 尝试 admin/admin123(globalSetup 复位后的初始态),失败再试 admin/E2eAdmin123
 *   - 若 must_change_password=true → API 改密到 E2eAdmin123,再用新密码登录
 *   - 最终把 token/user 塞进 localStorage
 *
 * 这种"双密码回退"让同一 playwright run 里多个 spec 共享 admin 账户,
 * 即便前面的 spec 把密码改到 E2eAdmin123,后面的 spec 仍能成功登录。
 * globalSetup 会在整轮 run 开始前把状态复位为 admin123,保证确定性起点。
 */
import type { Page, APIRequestContext } from "@playwright/test";

export const ADMIN_INITIAL_PWD = "admin123";
export const ADMIN_E2E_PWD = "E2eAdmin123";

interface LoginBody {
  access_token: string;
  user: {
    id: number;
    username: string;
    role: string;
    is_active: boolean;
    must_change_password: boolean;
  };
}

async function tryLogin(
  request: APIRequestContext,
  password: string,
): Promise<LoginBody | null> {
  const r = await request.post("/api/auth/login", {
    data: { username: "admin", password },
  });
  if (!r.ok()) return null;
  return (await r.json()) as LoginBody;
}

export async function loginAdmin(page: Page): Promise<LoginBody> {
  // 先试初始密码,失败再试 E2E 密码
  let pwd = ADMIN_INITIAL_PWD;
  let body = await tryLogin(page.request, ADMIN_INITIAL_PWD);
  if (!body) {
    pwd = ADMIN_E2E_PWD;
    body = await tryLogin(page.request, ADMIN_E2E_PWD);
  }
  if (!body) {
    throw new Error(
      "admin 登录失败:admin123 与 E2E 密码都被拒。globalSetup 未跑或 DB 异常。",
    );
  }

  let token = body.access_token;
  let user = body.user;

  if (user.must_change_password) {
    const r2 = await page.request.post("/api/auth/change-password", {
      headers: { Authorization: `Bearer ${token}` },
      data: { old_password: pwd, new_password: ADMIN_E2E_PWD },
    });
    if (!r2.ok()) {
      throw new Error(`admin 改密失败 (status ${r2.status()})`);
    }
    // 改密后旧 token 失效,用新密码重新登录
    const refreshed = await tryLogin(page.request, ADMIN_E2E_PWD);
    if (!refreshed) throw new Error("admin 改密后重新登录失败");
    token = refreshed.access_token;
    user = refreshed.user;
  }

  // 用 goto + evaluate 写 localStorage(而不是 addInitScript),
  // 避免后续 logout 场景里再次 goto 时被 init script 重新塞回 token
  await page.goto("/login");
  await page.evaluate(
    ({ t, u }) => {
      window.localStorage.setItem("auth:token", t);
      window.localStorage.setItem("auth:user", JSON.stringify(u));
    },
    { t: token, u: user },
  );

  return { access_token: token, user };
}

export async function clearAuth(page: Page): Promise<void> {
  await page.goto("/login");
  await page.evaluate(() => {
    window.localStorage.removeItem("auth:token");
    window.localStorage.removeItem("auth:user");
    window.localStorage.removeItem("auth:pendingPath");
  });
}
