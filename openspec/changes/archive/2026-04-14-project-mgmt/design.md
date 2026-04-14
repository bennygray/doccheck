## Context

M1 已落地登录、路由守卫、AuthContext、初始 admin seed 与强制改密。C2 归档时在 `backend/app/api/routes/projects.py` 保留了占位骨架(选项 A),在 `frontend/src/pages/ProjectsPlaceholderPage.tsx` 占位 `/projects`。C3 是 M2 的起点,后续 C4/C5/C6 都挂在 `Project` 这个实体上。

现状约束:

- C2 已提供 `get_current_user` 依赖、`require_role("admin")` 装饰器、`User` 模型、`pwd_v` 版本号校验中间件
- C1 已提供 alembic 迁移框架(当前 head=`0001_users`)、DB `pool_pre_ping`、统一的 `Base` 模型基类
- 前端已具备 `AuthContext` / `ProtectedRoute` / `RoleGuard` / `api.ts`(含 Authorization 头注入 + 401 回调)
- 项目粒度决策:C3 不引入 bidder/file/detection 任何实体,但详情页要为 C4+ 预留占位区

关键用户决策(2026-04-14 本次 session):

- 删除语义选 **软删除** A 方案(与 execution-plan.md §C3 一致,override user-stories.md US-2.4 的硬删文案)
- 归档时同步修订 user-stories.md US-2.4

## Goals / Non-Goals

**Goals:**

- 使 reviewer 能够创建/查看自己的项目列表,看详情,软删项目
- 使 admin 能够查看所有项目、软删任意项目
- 列表支持分页(size=12)、状态/风险筛选、关键词搜索(name + bid_code 模糊)
- 所有查询天然过滤软删记录,避免数据泄露
- 为 C4+ 预留接口:详情返回体含 `bidders / files / progress` 占位字段;`status` / `risk_level` 字段建好但仅 C3 范围内取 `draft` / `null`

**Non-Goals:**

- 不做项目重命名/编辑(US-2.x 未要求,延到 M4 admin 范围)
- 不做软删恢复接口(延到 C17 admin-users)
- 不做项目协作/多 owner(US-2.x 未要求)
- 不做磁盘文件清理(C3 阶段项目无物理文件关联;清理落到 C1 数据生命周期任务 + C4 上线后实装)
- 不引入状态机库(status 是简单字段枚举,转移逻辑延到 C6 detect-framework)
- 不引入乐观锁/version 字段(C3 无并发写场景)
- 不做批量删除/批量操作(US-2.x 未要求)

## Decisions

### D1. 软删除实现 = `deleted_at TIMESTAMP NULL` 列 + 查询层过滤

**选择**: `projects` 表加 `deleted_at` 列(默认 NULL);`DELETE` 端点置 `deleted_at = now()`;所有 SELECT 语句强制 `WHERE deleted_at IS NULL`。

**替代方案**:

- 独立 `projects_deleted` 归档表 — **拒绝**,迁移脏复杂,与 C17 潜在恢复接口耦合难处理
- `is_deleted BOOLEAN` — **拒绝**,布尔字段丢失"何时删除"的审计信息
- SQLAlchemy `@event.listens_for` 全局过滤 — **拒绝**,隐式行为难调试,reviewer 专用的 `owner_id` 过滤也要在同一层处理,索性写显式 query helper

**落地约束**:

- 在 `backend/app/models/project.py` 内定义一个 `get_visible_projects_query(db, current_user, include_deleted=False)` helper,所有读取路径必经此函数,避免"忘加过滤"的回归风险
- L1 单元测试要显式构造"软删记录 + 默认查询应不返回"的用例,锁死回归

### D2. 权限过滤下沉到查询层而非中间件

**选择**: 在 `get_visible_projects_query` 里,根据 `current_user.role`:
- reviewer → `WHERE owner_id = current_user.id`
- admin → 不加 owner 过滤
详情端点 `GET /{id}` 也走同一函数(传 id 后再 `.filter_by(id=...)`)。

**替代方案**:

- 每个路由写一遍 `if role == "reviewer": filter(...)` — **拒绝**,重复代码易漏
- FastAPI 中间件统一改写 query — **拒绝**,request 级全局魔法,不直观
- Database Row-Level Security — **拒绝**,C3 单 DB 单 schema,RLS 过度工程

**副作用**:

- reviewer 访问别人项目的详情 → 查询返回 None → 统一 404(与 US-2.3 "非 owner 的审查员访问 → 404 数据隔离" 对齐)
- reviewer 删除别人项目 → 同上 404(非 403),避免泄露项目存在性

### D3. 状态字段 = VARCHAR + 应用层枚举,不引状态机

**选择**: `projects.status VARCHAR(32) NOT NULL DEFAULT 'draft'`;Python 侧用 `class ProjectStatus(str, Enum)` 校验;C3 范围内只合法值 `draft`(其他值保留字符串,给 C6 推进用)。

**替代方案**:

- `ENUM` 数据类型 — **拒绝**,迁移时加枚举值是表级锁,不够灵活;SQLite 兼容差(CI 可能用 SQLite)
- transitions / python-statemachine 库 — **拒绝**,C3 还没有真实转移边;引进去反而绑死后续灵活度

### D4. `max_price` 存储 = DECIMAL(18, 2)

**选择**: 金额列用 `Numeric(18, 2)`(SQLAlchemy)→ Postgres `NUMERIC(18, 2)`。Pydantic schema 用 `condecimal(ge=0, max_digits=18, decimal_places=2)`。

**替代方案**:

- `FLOAT` — **拒绝**,浮点精度问题,与 C11/C12 报价分析未来对比会失真
- `BIGINT`(分单位) — **拒绝**,要求前端也做整数分换算,复杂度外溢;本项目报价精度到元(两位小数)够用

### D5. 分页参数 = `page + size`,不用游标

**选择**: query 参数 `?page=1&size=12`;返回 `{"items": [...], "total": N, "page": 1, "size": 12}`。默认 size=12(与 US-2.2 AC-5 对齐);`size` 上限 100 做后端校验。

**替代方案**:

- 游标分页 — **拒绝**,C3 项目量级 << 1000,offset 性能足够;游标分页 UI 复杂
- `limit / offset` 原始名 — **拒绝**,与前端常用语义不符;`page / size` 更直观

### D6. 前端表单校验 = HTML + 简单自定义,不引 form 库

**选择**: `react-hook-form` / `formik` 不引入;用原生 `<form onSubmit>` + 本地 `useState` + 简单校验函数。

**理由**:

- C3 表单字段少(4 个),校验规则简单
- 遵循 C2 同样的朴素前端风格(`LoginPage` / `ChangePasswordPage` 均未引 form 库)
- 引入 form 库成本远大于收益

### D7. L3 主线 spec 结构 = 一条端到端串联,不拆多文件

**选择**: `e2e/tests/c3-project-crud.spec.ts` 单文件,按顺序 login → create → list(筛选/搜索) → detail → delete → verify-gone。复用 C2 的 `loginAdmin(page)` helper。

**替代方案**:

- 按操作拆成 4 个 spec — **拒绝**,spec 间状态依赖明显,拆开反而要大量 fixture 恢复
- 每个场景都拆独立 spec — **拒绝**,workers=1 串行运行下,单文件更快;且 C3 没有 C2 那种"改密污染"的跨 spec 副作用

### D8. 并发创建同名项目 = 直接允许,不做幂等

**选择**: `projects.name` 不加 UNIQUE 约束,不做 "同 owner 同名合并" 逻辑。两次同名请求生成两条独立记录。

**理由**: US-2.1 AC-5 明确"同一用户可创建多个同名项目(不做唯一性校验)";execution-plan §C3 兜底"并发创建同名项目幂等"与 US-2.1 冲突,以 US-2.1 为准(更具体、更新)。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 软删过滤忘记加在新查询路径上,导致数据泄露 | 强制所有读取路径走 `get_visible_projects_query`;L1 显式回归用例;Code review 时重点看 `SELECT FROM projects` 的 grep 结果 |
| reviewer 访问别人项目返回 404 → 可能被理解为 bug | 在 API 文档(OpenAPI docstring)显式说明"为防止泄露项目存在性,非 owner 访问返回 404";前端不需要处理 403 分支 |
| `status=analyzing` 拒删逻辑在 C3 阶段无法真实触发 | L2 测试通过 fixture 直接 `UPDATE projects SET status='analyzing'` 构造,验证 409;C6 完成后该路径天然被覆盖 |
| 前端列表首次加载空状态 vs 加载中区分 | 用显式 loading state(`isLoading: boolean`),空 `items` + `!isLoading` 才渲染"暂无项目"引导,避免闪烁 |
| alembic `0002_projects` 与未来 C4 的 `0003_bidders` 迁移冲突 | C3 迁移只建 `projects` 表,不加任何反向 FK;C4 迁移时在 `bidders` 表加 `project_id FK`,不需要 alter `projects` |
| `risk_level` 字段 C3 内恒为 null 但要在筛选中支持 | 筛选实现 `if risk_level: query.filter(Project.risk_level == risk_level)`;C3 范围内该筛选永远返回空,L2 验证"带 `risk_level=high` 参数返回空列表"即可,不假阳 |
| `deleted_at` 排序会把 NULL 排首/尾影响默认列表顺序 | 默认排序 `created_at DESC`,不 ORDER BY `deleted_at`;过滤已隔离软删记录,无影响 |

## Migration Plan

1. `alembic revision -m "projects" --rev-id 0002_projects` 生成空模板
2. 手写 upgrade:`CREATE TABLE projects (...)` + 索引 `(owner_id, deleted_at, created_at)` 联合索引支持 reviewer 列表主路径
3. 手写 downgrade:`DROP TABLE projects`
4. `alembic upgrade head` 本地验证
5. C3 归档时迁移随 commit 进入主干;部署侧 `alembic upgrade head` 一行推到生产

**回滚策略**: 如 C3 实装出严重 bug,可 `alembic downgrade 0001_users`(projects 表被直接 DROP)。因 C3 归档前 C4+ 不会开启,`projects` 表无下游依赖,回滚安全。

## Open Questions

无。所有关键决策已在 propose 阶段与用户敲定。
