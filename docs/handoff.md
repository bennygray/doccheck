# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M1 完成**(2/2 change 归档);M2 待启动 |
| 当前 change | 待 C3 `project-mgmt` propose |
| 当前任务行 | N/A |
| 最新 commit | 待本次 archive commit(`归档 change: auth(M1)`) |
| 工作区 | 大量 C2 未提交改动:backend(User 模型/auth 服务/路由/迁移/reset 脚本)+ frontend(AuthContext/ProtectedRoute/RoleGuard/LoginPage/ChangePasswordPage/ProjectsPlaceholderPage/重写 App.tsx & api.ts)+ e2e(auth helper/globalSetup/新 spec/C1 smoke 适配)+ specs/changes 归档 + handoff/execution-plan 更新 |

---

## 2. 本次 session 关键决策(2026-04-14,C2 apply 阶段)

### 设计层面(propose 敲定)
- **改密旧 token 立即失效 = `pwd_v` 版本号**(JWT claim + 中间件比 DB `password_changed_at` 毫秒时间戳);不引入 Redis 黑名单,零新基础设施
- **账户锁定 = DB 字段 `locked_until` + `SELECT FOR UPDATE`**;TTL 过后自动解锁
- **初始 admin = alembic data migration + `ON CONFLICT DO NOTHING`**;密码哈希在迁移里动态算不硬编码
- **前端状态管理 = React Context + localStorage**;不引 zustand/redux(与 C1 D7 延续)
- **前端路由 = `react-router-dom` v7**(C1 package.json 已装但未用,C2 首次启用)
- **返回码约定**:401(无 token/过期/签名错/pwd_v 不符)、403(角色不足/禁用)、429(锁定)、400(old_password 错)、422(新密码不合规)

### apply 阶段就地敲定
- **pwd_v 精度 = 毫秒**(秒级会在同一秒内 fixture 插入+改密碰撞,使 `test_old_token_invalidated_after_password_change` 漏检)
- **L3 串行运行 workers=1**(auth-login.spec.ts 改密会污染 admin 状态;搭配 `afterAll` 复位 + `loginAdmin` 双密码回退 + globalSetup 每 run 前重置)
- **E2E admin 复位 = backend python 脚本**(`backend/scripts/reset_admin_for_e2e.py` 直接操作 DB;通过 execSync 在 playwright globalSetup 内调用)
- **admin-only L2 测试路由 = 测试文件内构造独立 FastAPI app**(`_build_test_app()`),避免污染生产 app
- **SECRET_KEY 默认值保留占位** `change-this-in-production`;生产部署必须 env 覆盖(README/env 已提示)

### 实施阶段关键技术坑
- **passlib 1.7.4 与 bcrypt 5.0.0 self-test 不兼容**(`ValueError: password cannot be longer than 72 bytes`):pyproject pin `bcrypt>=4.0,<4.1`
- **pwd_v 秒级精度**:fixture 插入 admin 和改密调用在同一秒内,`int(timestamp())` 相等 → 旧 token 没失效。改为 `int(timestamp() * 1000)` 毫秒精度
- **React batching + `logout+navigate` 时序**:ChangePasswordPage 在改密后 `logout()` 与 `navigate('/login')` 同 tick 批处理,短暂 re-render 使 ProtectedRoute 在 `/change-password` 触发并写入 pendingPath 污染。**双层防御**:`logout()` 同步清 `auth:pendingPath`;ProtectedRoute 写 pendingPath 时排除 `/login` 与 `/change-password`
- **Playwright `addInitScript` 每次 goto 重放**:loginAdmin 用 addInitScript 塞 localStorage 后,logout 后再 `goto('/projects')` 会被重新塞回 token → 无法模拟登出状态。改用 `page.goto('/login') + page.evaluate(localStorage.setItem)`
- **auth-login 改密污染后续 spec**:`afterAll` 调 `scripts.reset_admin_for_e2e` 复位 + `loginAdmin` 双密码回退(先试 admin123 再试 E2eAdmin123)+ `workers: 1` 串行
- **alembic versions 目录原本为空**,C2 是首个业务迁移(C1 只验证框架可用);用 revision id `0001_users`

---

## 3. 待确认 / 阻塞

- 无硬阻塞,M1 已全绿。
- **Follow-up**(非阻塞):Docker Desktop kernel-lock 问题仍在;真实 `docker compose up` 验证待解决后回补
- **Follow-up**:生产部署前必须 env 覆盖 `SECRET_KEY`、`AUTH_SEED_ADMIN_PASSWORD`;运维上线 checklist 需要记录(不在 C2 范围)

---

## 4. 下次开工建议

**一句话交接**:
> M1 完成(C1 `infra-base` + C2 `auth` 均已归档),L1/L2/L3 合计 65 pass 0 fail,M1 凭证在 `e2e/artifacts/m1-demo-2026-04-14.md`。下一步 `/opsx:propose` 开 C3 `project-mgmt`(项目 CRUD 分页筛选搜索)。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M1 已完成(C1 infra-base + C2 auth 均归档)。
下一步开 C3 project-mgmt:项目创建/列表(分页+筛选+搜索)/详情/软删除。
对应 docs/user-stories.md US-2.1~US-2.4;参考 docs/execution-plan.md §3 C3 小节。
backend/app/api/routes/projects.py 是 C1 保留的占位骨架(选项 A),C3 propose 时按"现状改造"处理。
所有业务路由都要挂 Depends(get_current_user);admin 专属挂 require_role("admin")。
请先读 docs/handoff.md 确认现状,然后 openspec-propose 为 C3 生成 artifacts。
tasks.md 按 CLAUDE.md OpenSpec 集成约定打 [impl]/[L1]/[L2]/[L3]/[manual] 标签。
```

**C3 前的预备条件(已就绪)**:
- `users` 表 + `admin` seed 已入 DB;`get_current_user` / `require_role` 依赖可直接注入
- 前端 `AuthContext` / `ProtectedRoute` / `RoleGuard` 已就位,`/projects` 路径占位页 `ProjectsPlaceholderPage.tsx` 待替换为真实项目列表
- `api.ts` 扩展用法已确立(自动挂 `Authorization` 头 + 401 回调),C3 加 `api.listProjects/createProject/...` 沿用现有骨架
- `backend/tests/fixtures/auth_fixtures.py` 的 `seeded_admin/reviewer/auth_client` 可被 C3 L2 复用,省 fixture 重造
- L3 `loginAdmin(page)` helper 可被 C3 所有需要登录态的 spec 复用

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-14 | **C2 `auth` 归档(M1 完成)**:L1/L2/L3 合计 65 pass 0 fail;JWT + 失败计数+锁定 + 强制改密(pwd_v 毫秒) + 路由守卫 + AuthContext + 前端 3 页面;M1 凭证 4 张截图 `e2e/artifacts/m1-demo-2026-04-14/` |
| 2026-04-14 | C2 `auth` propose 完成:4 artifact,7 Requirement + 22 Scenario;pwd_v 方案替 Redis 黑名单 |
| 2026-04-14 | **C1 `infra-base` 归档**:14 pass 0 fail;本地 PostgreSQL 替 Docker;LLM 适配层/SSE/DB pool_pre_ping/生命周期 dry-run/三层测试脚手架 全部落地 |
| 2026-04-14 | C1 `infra-base` propose 完成(4 个 artifact);C1 范围收敛,异步任务框架移至 C6 |
| 2026-04-14 | 首版 Handoff 落地,配合 execution-plan.md + CLAUDE.md 测试标准一起上线 |
