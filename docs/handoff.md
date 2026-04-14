# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | M2 进行中(C3 已归档,1/3) |
| 当前 change | 待 C4 `file-upload` propose |
| 当前任务行 | N/A |
| 最新 commit | 待本次 archive commit(`归档 change: project-mgmt(M2)`) |
| 工作区 | C3 全量改动:backend(Project 模型/schema/路由改造/迁移 0002/auth_fixtures 扩展)+ frontend(types/api 扩展/3 个新页/App 路由/删除 Placeholder)+ tests(L1×40 / L2×30 / L3×2)+ specs/changes 归档 + handoff/user-stories 更新 |

---

## 2. 本次 session 关键决策(2026-04-14,C3 propose + apply 阶段)

### 设计层面(propose 敲定)

- **删除语义 = 软删除** `deleted_at TIMESTAMP NULL`(选项 A);与 `docs/execution-plan.md` §C3 验证场景 4 一致;同步**修订** `docs/user-stories.md` US-2.4(原"硬删")
- **权限过滤下沉到查询层**(`get_visible_projects_stmt` helper),所有读取路径必经此函数,杜绝"忘加过滤"
- **reviewer 访问他人项目 = 404 而非 403**(防项目存在性泄露)
- **status 字段 = VARCHAR + 应用层枚举**(不引状态机库;C6 推进状态时只改 helper 不改字段类型)
- **金额精度 = `Numeric(18, 2)`**(精度需求到元/2 位小数,与 C11/C12 报价分析未来对比对齐)
- **分页 = page+size**(默认 size=12,上限 100;不上游标)
- **不引 form 库**(列表/创建/详情全部原生 useState,与 C2 LoginPage/ChangePasswordPage 风格一致)
- **L3 主线 = 单 spec 串联**(`c3-project-crud.spec.ts` 单文件 8 步;不拆 4 个 spec 避免状态恢复成本)
- **同名项目 = 直接允许**(US-2.1 AC-5 明确;execution-plan "幂等"以 US 为准)

### apply 阶段就地敲定

- **size 上限策略锁死 = 422**(spec.md 留二选一,L2 选拒绝;FastAPI Query `le=100` 自动返 422)
- **`clean_users` fixture 扩展清 projects**(放在 yield 前后,FK 依赖顺序 `delete projects → delete users`):C2 fixture 文件加 4 行,使所有 C2/C3/未来新表共享同一清理入口
- **C4+ 占位字段 = ProjectDetailResponse 默认值**(`bidders=[] / files=[] / progress=null`),不在路由层手填,避免 C4 上线时遗漏更新
- **smoke-home.spec.ts 适配新 ProjectListPage**(删 `health-status` 测点;h1 由"围标检测系统"改"项目列表"):随 C3 一起进 commit,不留出回归
- **detail/list 共享 `_fetch_visible_project` helper**(取行后统一 404),避免 reviewer-vs-others 的判断重复实现

### 实施阶段关键技术坑

- **L2 第一次跑全红 = FK 违反**:`clean_users` 在 yield 后跑 `DELETE FROM users` 时,projects 表持有 FK,asyncpg 报 `ForeignKeyViolationError`。Fix:`auth_fixtures.py` 的 `clean_users` 在清 users 前先清 projects(C3 是首张子表,后续每张子表加进来都要往这里加一行 delete)
- **删 `ProjectsPlaceholderPage` 触发 L3 smoke 回归**:`smoke-home.spec.ts` 依赖 `data-testid="health-status"` 与 `<h1>围标检测系统</h1>`。修复在同一 PR/commit 里完成:适配新 h1("项目列表")+ 移除 health-status 断言(改为只测 `/api/health` 代理可达性,不再要求前端展示)
- **window.confirm 在 Playwright 下默认 cancel**:c3 spec 里 `beforeEach` 注册 `page.on("dialog", d => d.accept())` 一次性解决所有删除/警告对话框
- **vite.config.ts 预存在 ts 错误**:`{ test: ... }` 不在 UserConfigExport 类型里(vitest 类型未合并);C3 范围内未触碰,留作 follow-up
- **`mapped_column` 写错位的笔误**:第一稿在 Project 模型里把 `from sqlalchemy.orm import Mapped` 放进了类内,然后 `id: Mapped_int = None` 占位 — 立刻发现并整体重写为标准 import 顶部 + 类体只放字段定义。教训:模型类不要嵌套 import

### 文档联动

- **修订 `docs/user-stories.md` US-2.4**:AC-3 由"硬删除并清盘" → "软删除(`deleted_at`)+ 文件清理移交生命周期任务";新增 AC-4 "非 owner 返 404 防存在性泄露";追加 `[Change History]` 行注明 C3 修订
- **execution-plan.md** 暂未追加 §6 计划变更行(本次未调整粒度/顺序,仅落地 C3 既定计划,无需写入)

---

## 3. 待确认 / 阻塞

- 无硬阻塞,M2 进度 1/3。
- **Follow-up**(非阻塞):`frontend/vite.config.ts` 的 `test` 字段类型错误(vitest 类型未合并到 UserConfigExport);不影响构建/测试运行,可在 C4 顺手修
- **Follow-up**(非阻塞):`e2e/tests/auth-login.spec.ts` 写截图到 `e2e/artifacts/m1-demo-2026-04-14/`,会在每次 L3 run 覆盖 M1 凭证图(本次 C3 已手动还原 03-projects.png)。建议 C4 顺手把该 spec 的截图路径改为非 M1 目录,或用 env flag 控制只在 manual 模式截图
- **Follow-up**:Docker Desktop kernel-lock 仍在;真实 `docker compose up` 验证待解决后回补
- **Follow-up**:生产部署前必须 env 覆盖 `SECRET_KEY` / `AUTH_SEED_ADMIN_PASSWORD`(C2 已记)

---

## 4. 下次开工建议

**一句话交接**:
> C3 `project-mgmt` 已归档(L1 76 / L2 51 / L3 10 = 137 全绿,C3 新增 72 个用例)。M2 进度 1/3。下一步 `/opsx:propose` 开 C4 `file-upload`(投标人 CRUD + 压缩包上传含 zip-bomb/路径穿越防护 + 加密包 + 报价规则配置)。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M2 进度 1/3:C3 project-mgmt 已归档。
下一步开 C4 file-upload:投标人 CRUD + 压缩包上传(zip-bomb/路径穿越/加密包)+ 报价规则配置。
对应 docs/user-stories.md US-3.1~3.4 + US-4.1 + US-4.4;参考 docs/execution-plan.md §3 C4 小节。
backend/app/api/routes/documents.py 是 C1 保留的占位骨架,C4 propose 时按"现状改造"处理。
所有业务路由都要挂 Depends(get_current_user);文件上传走 multipart 表单,需在 nginx/uvicorn 层定上限。
请先读 docs/handoff.md 确认现状,然后 openspec-propose 为 C4 生成 artifacts。
tasks.md 按 CLAUDE.md OpenSpec 集成约定打 [impl]/[L1]/[L2]/[L3]/[manual] 标签。
```

**C4 前的预备条件(已就绪)**:

- `projects` 表 + `Project.id` FK 锚点已就位,C4 可直接 `bidders.project_id FK → projects.id`
- `get_visible_projects_stmt` helper 模式可被 C4 复用,做"投标人可见性"(挂在投标人所属项目的 owner 身上)
- 前端 `ProjectDetailPage.tsx` 已留 `bidders-placeholder / files-placeholder` 两个占位区,C4 直接替换 section
- L2 `auth_fixtures.clean_users` 清理已支持 projects 表;C4 加 bidders/files 表后,继续在同 fixture 按 FK 顺序往前加 `delete bidders / delete files`(已写入 fixture docstring 提示)
- L3 `loginAdmin(page)` + `c3-project-crud.spec.ts` 的 `page.on("dialog")` 模式可直接复用
- 后端依赖已装(C1 安装):`python-multipart`(form upload)、`pymupdf` / `python-docx` / `openpyxl`(C5 才用);C4 阶段需新增解压/加密包依赖(`py7zr` / `rarfile` 等),propose 阶段决策

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-14 | **C3 `project-mgmt` 归档(M2 进度 1/3)**:Project 模型 + 软删 + 权限隔离 + 分页筛选搜索;L1 76 / L2 51 / L3 10 = 137 pass;C3 新增 72 用例;同步修订 user-stories.md US-2.4(硬删→软删)|
| 2026-04-14 | C3 `project-mgmt` propose 完成:4 artifact,7 Requirement + 30 Scenario;软删 vs 硬删冲突由用户拍板选 A 软删 |
| 2026-04-14 | **C2 `auth` 归档(M1 完成)**:L1/L2/L3 合计 65 pass 0 fail;JWT + 失败计数+锁定 + 强制改密(pwd_v 毫秒) + 路由守卫 + AuthContext + 前端 3 页面;M1 凭证 4 张截图 `e2e/artifacts/m1-demo-2026-04-14/` |
| 2026-04-14 | C2 `auth` propose 完成:4 artifact,7 Requirement + 22 Scenario;pwd_v 方案替 Redis 黑名单 |
| 2026-04-14 | **C1 `infra-base` 归档**:14 pass 0 fail;本地 PostgreSQL 替 Docker;LLM 适配层/SSE/DB pool_pre_ping/生命周期 dry-run/三层测试脚手架 全部落地 |
