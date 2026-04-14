## Why

C1 `infra-base` 已归档,系统具备 DB/SSE/LLM 适配层/三层测试脚手架等"地基"。M1 里程碑的演示级判据是"默认账号登录进空壳系统",必须 C2 落地 auth 能力才能达成。同时 C3+ 的所有业务路由都需要 `get_current_user` 依赖注入,auth 是后续 15 个 change 的前置依赖。

本 change 对应 `docs/user-stories.md` US-1.1 ~ US-1.4 的全部 AC,以及 `docs/execution-plan.md` §3 C2 小节定义的 5 个验证场景。

## What Changes

- **后端**
  - 新增 `User` 模型与 `users` 表迁移(字段含 `login_fail_count`、`locked_until`、`must_change_password`、`password_changed_at`)
  - 新增 `auth` 服务模块:bcrypt 密码哈希(passlib)、JWT 编解码(python-jose HS256,载荷含 `pwd_v`)、登录失败计数/锁定状态机
  - 新增 `/api/auth/login`、`/api/auth/logout`、`/api/auth/me`、`/api/auth/change-password` 四个端点
  - 新增 FastAPI 依赖 `get_current_user`(校验 JWT 签名+过期+`pwd_v` 与 DB `password_changed_at` 一致)与 `require_role("admin")`(基于前者再校角色)
  - 新增 alembic data migration 创建 `admin/admin123`(`must_change_password=true`),使用 `ON CONFLICT DO NOTHING` 保证多次启动幂等
  - 新增 `backend/tests/fixtures/auth_fixtures.py`:共享的 auth fixture(测试用户 seed、token 生成、带权 client)

- **前端**
  - 安装 `react-router-dom`,App 切到路由模式
  - 新增 `/login`、`/change-password` 页
  - 新增 `AuthContext`(存 token+user+must_change_password,`localStorage` 持久化)、`<ProtectedRoute>` 组件、`<RoleGuard role="admin">` 组件
  - `api.ts` 扩展:自动挂 `Authorization: Bearer <token>`;收到 401 → 清 context + 重定向 `/login`
  - 占位"首页 `/`"改为 `/projects`(空壳页,真实内容由 C3 实现),满足 US-1.1 AC "登录后跳项目列表"

- **测试**
  - L1:密码哈希/JWT 编解码/失败计数状态机/锁定 TTL 状态机/前端 AuthContext/前端 ProtectedRoute
  - L2:登录全流程、5 次错密锁定、过期 token 401、admin 403、改密后旧 token 立即失效、seed 幂等
  - L3:登录 → 跳 `/projects`、admin 首次登录强制改密
  - manual:真实浏览器完成一次 "登录 → `/projects`" 演示,作为 M1 交付凭证(截图存 `e2e/artifacts/m1-demo-YYYY-MM-DD.png`)

## Capabilities

### New Capabilities

- `auth`: 用户认证与授权能力,包括登录/登出、JWT 签发与校验、失败计数与账户锁定、初始用户 seed、强制改密、路由守卫与角色鉴权

### Modified Capabilities

(无 — `infra-base` 不需要修改;C2 仅依赖其 DB/配置/测试脚手架)

## Impact

- **新增代码**
  - `backend/app/models/user.py`、`backend/app/schemas/auth.py`
  - `backend/app/services/auth/` (`password.py` + `jwt.py` + `lockout.py`)
  - `backend/app/api/routes/auth.py`、`backend/app/api/deps.py`(`get_current_user` / `require_role`)
  - `backend/alembic/versions/xxxx_create_users_and_seed_admin.py`
  - `backend/tests/unit/test_auth_*.py`、`backend/tests/e2e/test_auth_*.py`、`backend/tests/fixtures/auth_fixtures.py`
  - `frontend/src/contexts/AuthContext.tsx`、`frontend/src/components/ProtectedRoute.tsx`、`frontend/src/components/RoleGuard.tsx`
  - `frontend/src/pages/LoginPage.tsx`、`frontend/src/pages/ChangePasswordPage.tsx`、`frontend/src/pages/ProjectsPlaceholderPage.tsx`
  - `e2e/tests/auth-*.spec.ts`

- **新增依赖**
  - 后端依赖已在 `pyproject.toml` 声明但未使用:`python-jose[cryptography]`、`passlib[bcrypt]` — 本 change 首次真正引入
  - 前端:`react-router-dom`(首次引入)

- **API 表面**:4 个 `/api/auth/*` 端点(均为 C2 自有,后续 change 不修改);所有业务路由统一使用 `Depends(get_current_user)` / `Depends(require_role("admin"))`

- **DB 表**:`users`(新建)

- **配置项**(`backend/app/core/config.py` 扩展)
  - `SECRET_KEY`(已存在,C2 首次真正使用;`.env.example` 提示生产必须覆盖)
  - `ACCESS_TOKEN_EXPIRE_MINUTES`(已存在,默认 24h)
  - `AUTH_LOCKOUT_THRESHOLD`(默认 5)
  - `AUTH_LOCKOUT_TTL_MINUTES`(默认 15)
  - `AUTH_SEED_ADMIN_USERNAME`(默认 `admin`)、`AUTH_SEED_ADMIN_PASSWORD`(默认 `admin123`,`.env.example` 注明生产必改)

- **范围边界(显式不做)**
  - 不做用户管理 CRUD(属 C17 `admin-users`)
  - 不做规则配置(属 C17)
  - 不做"禁用用户立即踢下线"(仅登录时拒,属 C17 session 管理范围)
  - 不做前端复杂表单恢复(US-1.3 AC5 的 localStorage 基础缓存落地;结构化表单恢复由 C3/C15 遇到再补)
  - 不做 refresh token(24h TTL 够用,避免过度设计)
