## Context

C2 `auth` 在 C1 `infra-base` 之上实现用户认证与授权能力,覆盖 `docs/user-stories.md` US-1.1 ~ US-1.4。这是 M1 里程碑的最后一个 change,归档后即可演示"默认账号登录进空壳系统"。

**前置就绪(来自 C1)**
- PostgreSQL 16 本地服务已跑,`documentcheck` 数据库已建
- SQLAlchemy 2.x async engine(`db/session.py`)、Alembic 迁移框架可用
- `backend/app/core/config.py` 已有 `secret_key` / `access_token_expire_minutes` 占位字段,C2 首次真正启用
- `pyproject.toml` 已声明 `python-jose[cryptography]` / `passlib[bcrypt]` 但未用,C2 首次引入
- 前端 Vite + React 19 + TS 6 完整骨架;`src/services/api.ts` 基于 `fetch` 封装(无 axios);路由:**当前 `App.tsx` 用手写条件渲染区分 `/demo/sse`,无 react-router**,C2 首次引入 `react-router-dom`
- 三层测试脚手架已就位:`backend/tests/unit|e2e/`、`frontend/src/**/*.test.tsx`、项目根 `e2e/`
- LLM mock 入口约定(本 change 不涉及 LLM)

**约束**
- 不引入新基础设施(Redis/Celery/session store)
- 不与 C17 `admin-users` 范围重叠(用户 CRUD、session 在线管理不做)
- 遵循 CLAUDE.md OpenSpec 集成约定:tasks 标签化,末尾总汇 `[L1][L2][L3]`
- 遵循"每个环节都要有兜底方案"约束(见 §Risks)

## Goals / Non-Goals

**Goals**
- 默认账号可登录,登录成功返回 JWT + 跳转到 `/projects`(空壳页)
- 错密 5 次账户锁定 15 分钟,TTL 过后自动解锁
- JWT 过期自然失效(24h TTL),访问 API 返 401
- 审查员(reviewer)访问 `/admin/*` 返 403
- admin 首次登录强制跳 `/change-password`,改密后旧 token **立即** 失效
- 所有行为有对应 L1/L2/L3 测试覆盖

**Non-Goals**
- 用户管理 CRUD / 规则配置(C17)
- 禁用用户立即踢下线(C17)
- 前端结构化表单数据恢复(C3/C15 按需补)
- refresh token / 多设备登录 / SSO(本期不做)
- 密码找回 / 邮箱验证(本期不做,admin 可手动重置 — C17 范围)

## Decisions

### D1. JWT 库与算法:python-jose + HS256
- **选择**:`python-jose[cryptography]`(pyproject 已声明),HS256 对称签名,`SECRET_KEY` 从 `config.py` 读取
- **替代方案**:`PyJWT`、`authlib`、RS256 非对称
- **理由**:pyproject 已声明 jose 避免无谓切换;HS256 + 单服务部署无需分发公钥,对称密钥足够;RS256 留给后续多服务拆分时再升级

### D2. 密码哈希:passlib + bcrypt
- **选择**:`passlib[bcrypt]`(pyproject 已声明),`CryptContext(schemes=["bcrypt"], deprecated="auto")`
- **理由**:bcrypt 是 OWASP 推荐;passlib 封装好升级路径(deprecated 自动识别旧哈希)
- **强度**:默认 12 rounds(passlib 默认),本期不调

### D3. 改密后旧 token 立即失效:pwd_v 版本号方案(不引入黑名单)
- **选择**:JWT 载荷带 `pwd_v: int(password_changed_at.timestamp())` claim;`get_current_user` 每次请求查 DB 比对 `pwd_v == int(user.password_changed_at.timestamp())`,不等即 401
- **替代方案**
  - Redis/内存黑名单:改密时把旧 jti 加黑名单直到过期 — 需要 Redis,违反"不引入新基础设施"
  - 仅短 TTL 不保证立即失效 — 违反 US-1.4 AC
  - 数据库 sessions 表 + 每次查 — 过度设计,与 C17 session 管理范围撞
- **理由**:users 表主键查询成本极低(~0.1ms),换来"零新基础设施 + 即时失效";首次引入 `password_changed_at` 字段后续还可服务 C17 的审计需求

### D4. 登录失败计数与锁定:原子化更新 + TTL 字段
- **选择**:`users` 表持字段 `login_fail_count INT NOT NULL DEFAULT 0` 与 `locked_until TIMESTAMPTZ NULL`
- **状态机**
  1. 密码错误 → `login_fail_count += 1`;若达阈值(默认 5) → `locked_until = now() + 15min`,同时清零计数(下次再错从 0 起算,避免永久锁)
  2. 登录时先看 `locked_until`:若 `locked_until > now()` → 429 并说明剩余时间;若 `locked_until <= now()` 或为 null → 放行校验
  3. 密码正确 → `login_fail_count = 0`、`locked_until = NULL`
- **并发处理**:用 `UPDATE ... RETURNING` 原子化(SQLAlchemy `with_for_update()` + commit 即可在单请求内同步);不引入分布式锁(单进程 uvicorn 场景够用,多进程扩展时改 `SELECT FOR UPDATE SKIP LOCKED` 即可)
- **替代方案**:Redis 计数 + TTL — 违反基础设施约束
- **通用错误信息**:用户名不存在与密码错误都返 401 + "用户名或密码错误",防用户名枚举;但**用户名不存在不累计锁定**(否则攻击者可故意触发合法用户锁定 → DoS);实现上 `user is None` 直接 return 401 不写 DB

### D5. 用户角色:admin | reviewer 两种,DB 用字符串字段
- **选择**:`role VARCHAR(16) NOT NULL`,应用层用 `Literal["admin", "reviewer"]`;**不用 enum 类型**(postgres enum 修改痛苦)
- **替代方案**:postgres `ENUM`、独立 roles 表
- **理由**:两角色短期不会扩;独立 roles 表是 C17 级别的权限系统设计,C2 过度设计

### D6. seed 管理员:alembic data migration(而非 app 启动 hook)
- **选择**:在创建 `users` 表的同一个 alembic 迁移里 `op.bulk_insert` 默认管理员;用原生 SQL `INSERT ... ON CONFLICT (username) DO NOTHING` 保证幂等
- **密码**:`admin123` 的 bcrypt 哈希 **不**硬编码到迁移文件,迁移里 `import` passlib 动态计算,避免"迁移文件暴露固定哈希"的观感问题
- **替代方案**:FastAPI `lifespan` 里起 task 检测并插入 — 运行时副作用,且每次启动都跑一遍
- **理由**:迁移一次性、可回滚、与 schema 强绑定;ON CONFLICT 幂等,多节点并发启动也安全
- **配置覆盖**:`AUTH_SEED_ADMIN_USERNAME/PASSWORD` 允许通过 env 覆盖默认值(例如生产环境)

### D7. 前端状态管理:React Context + localStorage,不引入 zustand/redux
- **选择**:`<AuthContext>` 提供 `{user, token, login, logout, setMustChangePassword}`;token 与 user 同步写 `localStorage` 以实现刷新持久化
- **替代方案**:zustand/redux-toolkit/react-query
- **理由**:C2 仅 auth 一个状态域,Context 足够;更复杂状态库留到 C3+ 业务数据增多时再评估;与 C1 D7 "前端骨架最小化"一致

### D8. 前端 axios interceptor 等价物:`fetch` wrapper + global 401 handler
- **选择**:`api.ts` 内部维护 `authStore`(从 Context 拿 token;exports `setAuthStore(store)`);每次请求自动挂 `Authorization: Bearer`;响应 401 → `authStore.logout()` + `window.location.assign('/login')`
- **替代方案**:引入 axios
- **理由**:现有 `api.ts` 已是 fetch 封装,加一层 interceptor 成本低;不引额外依赖
- **US-1.3 AC5 表单防丢失**:C2 实现最小版 —— 401 时 `localStorage.setItem('auth:pendingForm', location.pathname)`;登录成功后 Login 页检查该 key,有值则 `navigate(pendingPath)`(不做结构化表单数据序列化,避免与 C3/C15 具体表单实现耦合)

### D9. 路由与强制改密:react-router-dom v6
- **选择**:`react-router-dom@^6`;`<BrowserRouter>` + `<Routes>`;`<ProtectedRoute>` 包所有非 `/login` `/change-password` 路由
- **强制改密拦截**:`<ProtectedRoute>` 内检查 `user.must_change_password`:true 时若当前路径 !== `/change-password` → `<Navigate to="/change-password" replace />`
- **角色守卫**:`<RoleGuard role="admin">` 内部:`user.role !== "admin"` → `<Navigate to="/projects" replace />`

### D10. 测试 fixture 共享
- **后端**:`backend/tests/fixtures/auth_fixtures.py` 提供 `seeded_admin`(已写入 DB 的用户 ORM 对象)、`seeded_reviewer`、`admin_token`、`reviewer_token`、`authed_client`(httpx AsyncClient 预挂 token);L1 单测用不到 DB 的部分(纯密码/JWT 编解码)直接在 `tests/unit/` 用内联 mock 即可,不必经 fixture
- **前端**:`frontend/src/test-setup.ts` 已有(来自 C1);AuthContext 测试用 `render` + `<AuthProvider>` wrapper helper,放在 `src/contexts/test-utils.tsx`
- **L3 Playwright**:用 `page.request.post('/api/auth/login', ...)` 先拿 token → `page.addInitScript` 塞 localStorage;避免走 UI 登录拖慢冒烟。登录 UI 本身用独立 spec 走 UI

### D11. 失败锁定的"通用错误信息 vs 明确告知"
- **登录阶段**:错密、不存在用户、被禁用都返 401 + 通用文案,防枚举(US-1.1 AC2)
- **锁定触发后**:下一次登录返 429 + 明确告知"账户已锁定,剩余 X 分钟",利于合法用户知情(US-1.1 AC5)— 此时用户名存在已被前一次攻击确认,不再有枚举风险

### D12. 前端页面风格
- 最小化 CSS,继承 C1 `App.css` 风格;不引入 UI 组件库(MUI/Antd);表单原生 `<form>` + `<input>`
- **理由**:C2 不是 UI 打磨节点,能用即可;真正的设计系统等 M4 评估

## Risks / Trade-offs

- **[Risk] SECRET_KEY 默认值 `change-this-in-production`** → `.env.example` 与 README 都明确提示必改;部署时 key 若仍为默认值,在 `main.py` 启动 hook 里 WARN 日志(不 fail 启动,避免开发体验差);生产硬要求由运维流程保证
- **[Risk] `admin/admin123` 弱密码** → `must_change_password=true` 强制首次改;`.env.example` 提示生产用 env 覆盖
- **[Risk] bcrypt 慢导致暴力破解测试环境不稳** → 测试 fixture 在 `conftest.py` 里用 `passlib.context.CryptContext(schemes=["bcrypt_sha256"], bcrypt__rounds=4)`? 不,**不调强度**,避免测试与生产行为漂移;改为"测试时直接用预哈希的 seeded 用户",只在真正覆盖密码校验逻辑的测试里做一次真哈希,其他测试复用 `seeded_admin` fixture
- **[Risk] JWT `pwd_v` 每请求查 DB** → users 表 pk 查询 ~0.1ms,不构成瓶颈;后续若 QPS 高可加 `lru_cache`(TTL 30s)缓存 user,但 C2 不做
- **[Risk] 前端 `localStorage` 存 JWT 有 XSS 风险** → 当前无富文本/第三方脚本注入点;本期接受风险,由 CSP 头 + React 默认转义兜底;httpOnly cookie 方案留给生产化阶段(会引入 CSRF 额外复杂度)
- **[Risk] seed 在 alembic 里用 passlib 计算哈希,迁移可能慢** → 只跑一次,可接受;多节点并发 `alembic upgrade head` 通过数据库表锁串行化,`ON CONFLICT DO NOTHING` 兜住重复
- **[Risk] react-router v6 与 C1 当前 App.tsx 手写路由冲突** → C2 apply 时重写 `App.tsx` 的路由部分,保留 `/demo/sse` 作为 C1 遗留演示路径
- **[Risk] 403 vs 401 混淆** → 约定:无 token / 过期 token / 签名错 → **401**;token 有效但角色不足 → **403**;`is_active=false` → **403**(用户已存在,仅权限不足);被 `locked_until` 拦 → **429**
- **[Trade-off] 不做结构化表单恢复** → US-1.3 AC5 仅落"记住 pendingPath";真实表单数据恢复延后;被用户主动提出再补
- **[Trade-off] 单 secret_key 无 rotation** → 生产需要时通过停机切换 + 强制 relogin 处理;C2 不实现 key rotation 机制

## Migration Plan

本 change 在干净数据库上新建 `users` 表并 seed admin,无数据迁移需求。

**部署步骤(apply 阶段参考)**
1. 后端:`cd backend && uv sync`(拉 jose/passlib)→ `alembic upgrade head`(建 users 表 + seed admin)→ `uvicorn app.main:app --reload`
2. 前端:`cd frontend && npm install react-router-dom` → `npm run dev`
3. 访问 `http://localhost:5173` → 重定向 `/login` → 输入 `admin/admin123` → 拦截跳 `/change-password` → 改密后进 `/projects`

**回滚**
- `alembic downgrade -1` 删 users 表(含 admin)
- 前端 `git revert` 即可

**多节点/多次启动**:`ON CONFLICT DO NOTHING` 保证 seed 幂等。

## Open Questions

- **Q1**:`AUTH_LOCKOUT_TTL_MINUTES` 默认值 15,是否足够?
  - 建议:15 分钟(US-1.1 AC5 已明确),定为默认;生产可 env 覆盖
  - 决议时机:写 `config.py` 时敲定

- **Q2**:JWT `sub` 字段用 `user_id`(int)还是 `username`(str)?
  - 建议:`user_id`(稳定,username 改名不影响);JWT claim 同时带 `username` 便于日志
  - 决议时机:写 `services/auth/jwt.py` 时敲定

- **Q3**:`/api/auth/logout` 是否需要真做点事情(比如记录审计日志)?
  - 建议:C2 仅返 204,前端清 token 即可;审计日志属 C17 范围
  - 决议时机:写 auth 路由时,保持最小实现

- **Q4**:前端强制改密页是否允许用户"稍后再改"?
  - 建议:不允许(US-1.4 AC3 明确"屏蔽其他操作");改密成功后跳 `/projects`
  - 决议时机:写 ChangePasswordPage 时敲定
