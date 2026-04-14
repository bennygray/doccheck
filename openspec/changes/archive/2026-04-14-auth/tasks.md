## 1. User 模型与迁移

- [x] 1.1 `[impl]` 新增 `backend/app/models/user.py`:`User` ORM,字段 `id / username (unique) / password_hash / role (str) / is_active (bool) / must_change_password (bool) / login_fail_count (int) / locked_until (datetime | None) / password_changed_at (datetime) / created_at / updated_at`;在 `models/__init__.py` 暴露
- [x] 1.2 `[impl]` 新增 `backend/alembic/versions/0001_create_users_and_seed_admin.py`(versions 目录原本为空,C2 是首个业务迁移):建 `users` 表(带 `UNIQUE(username)` 索引)+ `INSERT ... ON CONFLICT (username) DO NOTHING` 写入默认 admin;密码哈希在迁移文件内用 `passlib.context.CryptContext` 动态算,不硬编码
- [x] 1.3 `[impl]` 验证:`alembic upgrade head` 成功,`users` 表存在,`SELECT * FROM users WHERE username='admin'` 有一行且 `must_change_password=true`

## 2. 密码哈希与 JWT 编解码

- [x] 2.1 `[impl]` 新增 `backend/app/services/auth/password.py`:封装 `hash_password(plain) -> str` 与 `verify_password(plain, hashed) -> bool`(passlib bcrypt)
- [x] 2.2 `[impl]` 新增 `backend/app/services/auth/jwt.py`:`create_access_token(user_id, role, pwd_v, username) -> str`、`decode_access_token(token) -> dict`;过期/签名错/格式错统一抛 `TokenInvalid` 自定义异常;HS256,`SECRET_KEY` 从 config 读
- [x] 2.3 `[impl]` 扩展 `backend/app/core/config.py`:新增 `auth_lockout_threshold: int = 5`、`auth_lockout_ttl_minutes: int = 15`、`auth_seed_admin_username: str = "admin"`、`auth_seed_admin_password: str = "admin123"`、`jwt_algorithm: str = "HS256"`

### 2.x 配套修复
- [x] 2.x1 `[impl]` `pyproject.toml` 加 `bcrypt>=4.0,<4.1` 约束(passlib 1.7.4 与 bcrypt 5.0.0 self-test 72 字节断言不兼容,apply 阶段发现)

## 3. 失败计数与锁定状态机

- [x] 3.1 `[impl]` 新增 `backend/app/services/auth/lockout.py`:`record_failure(user) -> bool`、`reset_failure(user) -> None`、`check_locked(user) -> timedelta | None`;状态机按 design.md D4 实现(达阈值设 `locked_until = now + TTL` 并清零计数)
- [x] 3.2 `[impl]` 并发:auth 路由在 SELECT 时用 `with_for_update()` 锁行(路由层而非 lockout 模块实现),避免丢更新

## 4. Auth 路由与依赖

- [x] 4.1 `[impl]` 新增 `backend/app/schemas/auth.py`:`LoginRequest`、`LoginResponse`、`UserPublic`、`ChangePasswordRequest`(pydantic validator:new_password ≥8 位 + 含字母 + 含数字)、`LockedResponse`
- [x] 4.2 `[impl]` 新增 `backend/app/api/deps.py`:`get_current_user`(从 `Authorization: Bearer` 解 JWT → 查 DB → 比对 `pwd_v` 与 `password_changed_at` → 失败返 401);`require_role(role)`(闭包工厂,基于 `get_current_user`,角色不符或 `is_active=false` 返 403)
- [x] 4.3 `[impl]` 新增 `backend/app/api/routes/auth.py`:`POST /api/auth/login` / `POST /api/auth/logout` / `GET /api/auth/me` / `POST /api/auth/change-password`;按 design.md D11 返回码约定实现(401/403/429/400/422)
- [x] 4.4 `[impl]` `backend/app/main.py` 注册 auth 路由(CORS 已 `allow_headers=["*"]` 放行 Authorization,无需改)

## 5. 前端路由与 AuthContext

- [x] 5.1 `[impl]` `react-router-dom@^7` 已在 `package.json` 存在(C1 遗留,C2 首次实际使用),无需 `npm install`
- [x] 5.2 `[impl]` 新增 `frontend/src/contexts/AuthContext.tsx`:`AuthProvider` + `useAuth()`;token+user 同步 `localStorage`;`authStorage` 模块级对象给 `api.ts` 消费避免循环 import;logout 时同时清 `auth:pendingPath`(防登出后 pending 污染)
- [x] 5.3 `[impl]` 新增 `frontend/src/components/ProtectedRoute.tsx`:未登录 → `<Navigate to="/login" replace />`;`must_change_password` 且路径非 `/change-password` → 强制跳 `/change-password`;`hydrated=false` 时返 null 防闪跳;pendingPath 写入时排除 `/login` 与 `/change-password`(避免 logout 重定向污染)
- [x] 5.4 `[impl]` 新增 `frontend/src/components/RoleGuard.tsx`:`role !== required` → `<Navigate to="/projects" replace />`
- [x] 5.5 `[impl]` 重写 `frontend/src/App.tsx`:`<Routes>` + `/login`、`/change-password`(含 ProtectedRoute)、`/projects`(空壳,含 ProtectedRoute)、`/demo/sse`(保留 C1 演示 + ProtectedRoute);`/` 与 `*` redirect 到 `/projects`;挂 `setOnUnauthorized` 让 401 时清 auth + 跳 `/login`;删除 `HomePage.tsx`(内容并入 ProjectsPlaceholderPage)
- [x] 5.6 `[impl]` 新增 `frontend/src/pages/LoginPage.tsx`:原生 form,提交 → `api.login` → 写 AuthContext;根据 `must_change_password` 与 `pendingPath` 决定 target
- [x] 5.7 `[impl]` 新增 `frontend/src/pages/ChangePasswordPage.tsx`:old/new/confirm 三字段 + 前端 ≥8 位/字母/数字 + 两次一致 即时校验;提交 → `api.changePassword` → `logout()` → 跳 `/login`
- [x] 5.8 `[impl]` 新增 `frontend/src/pages/ProjectsPlaceholderPage.tsx`:空壳页("项目列表将在 C3 实现"+"欢迎 {username}"+登出按钮+保留 C1 health 展示)
- [x] 5.9 `[impl]` 重写 `frontend/src/services/api.ts`:自动挂 `Authorization: Bearer`;401 → `authStorage.setPendingPath` + `authStorage.clear` + `onUnauthorized()`;新增 `login`/`logout`/`me`/`changePassword`;删除遗留 `uploadDocument/startAnalysis/getAnalysisResult/createProject`(C3/C4/C6 范围,C2 不再占位);`ApiError` 消息格式 `API error {status}: {detail}`
- [x] 5.10 `[impl]` 重写 `frontend/src/main.tsx`:`<AuthProvider>` 包 `<App>`(无需 `setAuthStore`,api.ts 直接从 `authStorage` 取)

## 6. 测试 fixture

- [x] 6.1 `[impl]` 新增 `backend/tests/fixtures/auth_fixtures.py`:`clean_users` / `seeded_admin` / `seeded_reviewer`、`admin_token` / `reviewer_token`、`auth_client` factory;在 `conftest.py` 的 `pytest_plugins` 注册
- [x] 6.2 `[impl]` 新增 `frontend/src/contexts/test-utils.tsx`:`renderWithAuth` + `primeAuthStorage` + `clearAuthStorage`

## 7. L1 测试

- [x] 7.1 `[L1]` `backend/tests/unit/test_auth_password.py`:hash 不等于明文、同明文多次 hash 盐不同、错误密码 verify 失败、畸形哈希 verify 返 False **(4 pass)**
- [x] 7.2 `[L1]` `backend/tests/unit/test_auth_jwt.py`:roundtrip、过期 token、签名篡改、畸形 token、pwd_v 透传 **(5 pass)**
- [x] 7.3 `[L1]` `backend/tests/unit/test_auth_lockout.py`:阈值以下不锁、达阈值锁+清零计数、TTL 过后解锁、reset 清状态、never locked 返 None **(5 pass)**
- [x] 7.4 `[L1]` `backend/tests/unit/test_auth_schema.py`:合规通过、短密码、无数字、无字母、空 old_password 拒绝 **(5 pass)**
- [x] 7.5 `[L1]` `frontend/src/contexts/AuthContext.test.tsx`:初始未登录、login 写入、logout 清除、从 localStorage 恢复、updateUser 保留 token **(5 pass)**
- [x] 7.6 `[L1]` `frontend/src/components/ProtectedRoute.test.tsx`:未登录重定向、登录渲染 children、must_change_password 强制跳转、在 /change-password 时不跳 **(4 pass)**

**L1 合计**:后端 **24 passed**(C1 5 + C2 19),前端 **12 passed**(C1 3 + C2 9)

## 8. L2 测试(API E2E)

- [x] 8.1 `[L2]` `backend/tests/e2e/test_auth_login.py`:成功登录、错密通用 401、不存在用户通用 401 且不累计、禁用用户 403 **(4 pass)**
- [x] 8.2 `[L2]` `backend/tests/e2e/test_auth_lockout.py`:5 次错密后 429 + retry_after_seconds + Retry-After 头、TTL 过后可登录并清零 **(2 pass)**
- [x] 8.3 `[L2]` `backend/tests/e2e/test_auth_token.py`:无/过期/畸形 token → 401、reviewer 访问 admin-only 403、admin 访问 200(通过内部 `_build_test_app()` 构造测试专用 admin-only 路由,不污染生产 app) **(5 pass)**
- [x] 8.4 `[L2]` `backend/tests/e2e/test_auth_change_password.py`:改密成功更新 flags、**改密后旧 token 立即 401**(pwd_v 毫秒精度)、错 old 400、弱 new 422、me 端点、logout 204 **(6 pass)**
- [x] 8.5 `[L2]` `backend/tests/e2e/test_auth_seed.py`:downgrade→upgrade 幂等,admin 仅一条且 must_change_password=true **(1 pass)**

**L2 合计**:**21 passed**(C1 3 + C2 18)

## 9. L3 测试(UI E2E)

- [x] 9.1 `[L3]` `e2e/tests/auth-login.spec.ts`:未登录 / → /login → admin/admin123 → 强制 /change-password → 改密 E2eAdmin123 → /login → 新密登录 → /projects → 登出 → /login(主流程顺带生成 4 张 M1 交付凭证截图到 `e2e/artifacts/m1-demo-2026-04-14/`);错误密码留在 /login
- [x] 9.2 `[L3]` `e2e/tests/auth-route-guard.spec.ts`:未登录访问 /projects 重定向;登录后访问 /demo/sse;登出后 /projects 再被拦截
- [x] 9.3 `[L3]` 配套基础设施:
  - `backend/scripts/reset_admin_for_e2e.py`:每次 run 前 globalSetup 执行,把 admin 复位到 admin123 + must_change_password=true
  - `e2e/global-setup.ts`:挂到 `playwright.config.ts`,`execSync uv run python -m scripts.reset_admin_for_e2e`
  - `e2e/fixtures/auth-helper.ts`:`loginAdmin(page)` 幂等(双密码回退)+ `clearAuth(page)`;用 `page.goto + evaluate` 塞 localStorage 而非 `addInitScript`(避免后续 goto 被重放污染)
  - `playwright.config.ts` 设 `workers: 1`(auth-login 改密会影响后续 spec,串行规避竞态)
  - `e2e/tests/smoke-home.spec.ts` / `smoke-sse.spec.ts` 适配 C1→C2 过渡:`/` 现在重定向 `/projects`,需先登录

**L3 合计**:**8 passed**(C1 adapted 3 + C2 5)

## 10. 手工验证(M1 交付凭证)

- [x] 10.1 `[manual]` M1 演示凭证:`e2e/artifacts/m1-demo-2026-04-14.md`(含 4 张实际截图的说明 + 重现命令 + 测试结果汇总);凭证本身可由 L3 测试自动重现(auth-login.spec.ts 主流程在关键点 `page.screenshot` 4 张)。`.gitignore` 已加白名单保留 `m1-demo-*`。`docs/execution-plan.md` §5.3 已写入里程碑凭证行

## 11. 总汇

- [x] 11.1 跑 `[L1][L2][L3]` 全部测试,全绿
  - L1 后端:`pytest backend/tests/unit/` → **24 passed**
  - L1 前端:`cd frontend && npm test` → **12 passed**
  - L2:`pytest backend/tests/e2e/` → **21 passed**
  - L3:`npm run e2e` → **8 passed**
  - **合计 65 pass,0 fail**
