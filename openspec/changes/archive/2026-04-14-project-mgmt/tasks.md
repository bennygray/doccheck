## 1. 后端数据层

- [x] 1.1 [impl] 新增 `backend/app/models/project.py`:`Project` 模型(字段按 spec "数据模型字段" Requirement);`deleted_at` 默认 NULL
- [x] 1.2 [impl] 在 `backend/app/models/project.py` 内实现查询 helper `get_visible_projects_query(db, current_user, include_deleted=False)`,统一处理软删过滤与角色过滤(reviewer owner_id 过滤 / admin 不过滤)
- [x] 1.3 [impl] 新增 `backend/alembic/versions/0002_projects.py`:`CREATE TABLE projects` + 联合索引 `(owner_id, deleted_at, created_at DESC)` + FK 到 `users.id`;含 downgrade DROP
- [x] 1.4 [impl] 本地执行 `alembic upgrade head` 与 `alembic downgrade 0001_users` 双向验证

## 2. 后端 Schema 与路由

- [x] 2.1 [impl] 新增 `backend/app/schemas/project.py`:`ProjectCreate` / `ProjectResponse` / `ProjectListResponse` / `ProjectDetailResponse`(后者含 `bidders=[]` `files=[]` `progress=null` 占位)
- [x] 2.2 [impl] `ProjectCreate` 字段校验:`name` constr(max=100, min=1)、`bid_code` constr(max=50)、`max_price` condecimal(ge=0, max_digits=18, decimal_places=2)、`description` constr(max=500)
- [x] 2.3 [impl] 改造 `backend/app/api/routes/projects.py`:
  - `POST /`:挂 `Depends(get_current_user)`;创建记录;返回 201
  - `GET /`:挂 `Depends(get_current_user)`;query 参数 `page / size / status / risk_level / search`;调用 helper;返回 `{items, total, page, size}`
  - `GET /{id}`:挂 `Depends(get_current_user)`;调用 helper.filter(id=id);不存在/他人项目/软删均 404;返回 `ProjectDetailResponse`
  - `DELETE /{id}`:挂 `Depends(get_current_user)`;status=analyzing → 409;置 `deleted_at=now()`;返回 204
- [x] 2.4 [impl] 路由注册确认 `backend/app/main.py`(或 router 聚合点)prefix=`/api/projects`

## 3. 前端 API 与类型

- [x] 3.1 [impl] 扩展 `frontend/src/types/index.ts`:`Project` / `ProjectListItem` / `ProjectDetail` / `ProjectCreatePayload` / `ProjectListQuery` / `ProjectListResponse` 类型
- [x] 3.2 [impl] 扩展 `frontend/src/services/api.ts`:新增 `listProjects(q) / createProject(p) / getProject(id) / deleteProject(id)` 四方法;复用 C2 已建的 axios 实例(Authorization 头注入 + 401 回调)

## 4. 前端页面

- [x] 4.1 [impl] 新增 `frontend/src/pages/projects/ProjectListPage.tsx`:真实列表 + 状态/风险筛选下拉 + 搜索框 + 分页控件 + "新建项目"按钮 + "删除"按钮(二次确认);空状态引导
- [x] 4.2 [impl] 新增 `frontend/src/pages/projects/ProjectCreatePage.tsx`:`/projects/new`;原生表单(4 字段)+ 本地 useState 校验 + 提交后 navigate 到详情页;max_price 不填时显示 US-2.1 提示文案
- [x] 4.3 [impl] 新增 `frontend/src/pages/projects/ProjectDetailPage.tsx`:`/projects/:id`;顶部基本信息 + 状态徽章;中间三个占位 Section("投标人 C4"/"文件 C4"/"检测进度 C6")显式标注尚未实现
- [x] 4.4 [impl] 更新 `frontend/src/App.tsx` 路由表:`/projects` → ProjectListPage(替换 ProjectsPlaceholderPage)、`/projects/new` → ProjectCreatePage、`/projects/:id` → ProjectDetailPage;三者均包 `<ProtectedRoute>`
- [x] 4.5 [impl] 删除 `frontend/src/pages/ProjectsPlaceholderPage.tsx`(由 ProjectListPage 替代,避免文件残留)

## 5. L1 单元+组件测试

- [x] 5.1 [L1] 新增 `backend/tests/unit/test_project_schema.py`:
  - `ProjectCreate` name 空/超长/合法
  - `max_price` 负数/超精度/合法
  - `bid_code` 超长
  - `description` 超长
- [x] 5.2 [L1] 新增 `backend/tests/unit/test_project_query.py`:
  - 构造 reviewer/admin + 未删/已删记录组合,调用 `get_visible_projects_query` 验证过滤正确性(含"忘加过滤回归用例")
- [x] 5.3 [L1] 新增 `frontend/src/pages/projects/ProjectListPage.test.tsx`:空态渲染;有数据渲染;点击筛选/搜索触发 query 变化(mock api)
- [x] 5.4 [L1] 新增 `frontend/src/pages/projects/ProjectCreatePage.test.tsx`:name 空不可提交;max_price 负数显示错误;未填 max_price 显示 US-2.1 提示文案
- [x] 5.5 [L1] 命令验证:`pytest backend/tests/unit/` 全绿 + `cd frontend && npm test` 全绿

## 6. L2 后端 API 级 E2E

- [x] 6.1 [L2] 新增 `backend/tests/e2e/test_projects_api.py`,复用 `backend/tests/fixtures/auth_fixtures.py` 的 `seeded_admin / reviewer / auth_client`
- [x] 6.2 [L2] 覆盖 spec "创建项目" 全部 6 个 Scenario
- [x] 6.3 [L2] 覆盖 spec "项目列表" 全部 9 个 Scenario(含 size 上限策略锁定 → 422 路线)
- [x] 6.4 [L2] 覆盖 spec "项目详情" 全部 5 个 Scenario
- [x] 6.5 [L2] 覆盖 spec "软删除项目" 全部 5 个 Scenario(含 fixture 手动置 status=analyzing 测 409)
- [x] 6.6 [L2] 覆盖 spec "角色与鉴权" 3 个 Scenario(过期 token / 改密后旧 token / reviewer 全端点可达)
- [x] 6.7 [L2] 覆盖 spec "为 C4+ 预留的占位字段" 2 个 Scenario
- [x] 6.8 [L2] 命令验证:`pytest backend/tests/e2e/test_projects_api.py` 全绿(30 pass);完整 L2 全绿(51 pass,无 C2 回归)

## 7. L3 UI 级 E2E

- [x] 7.1 [L3] 新增 `e2e/tests/c3-project-crud.spec.ts`,复用 `e2e/fixtures/auth-helper.ts` 的 `loginAdmin(page)`(实际路径与 tasks 原文一致;C2 已建)
- [x] 7.2 [L3] 主线 spec:登录 → 访问 `/projects` → 点击新建 → 填表提交 → 跳详情页断言基本字段 → 返回列表看到该项目 → 搜索关键词命中 → 筛选 status=draft 命中 → 点击删除 → 确认 → 列表消失;附加场景:空白 name 提交显示错误
- [x] 7.3 [L3] 命令验证:`npx playwright test` 全绿(10 pass,含 C1/C2/C3);未触发 flaky,无需降级。同步修复 `smoke-home.spec.ts` 因 ProjectsPlaceholderPage 删除导致的 testid 回归

## 8. 文档联动

- [x] 8.1 [manual] 修订 `docs/user-stories.md` US-2.4:AC-3 "硬删除,级联删除..." 改为 "软删除,置 deleted_at;磁盘文件清理交由数据生命周期任务(C1 骨架 + C4 落地)";测试验证点与后端 API 测试表述同步更新;新增 AC-4 "非 owner 返 404 防存在性泄露";追加 [Change History] 行
- [x] 8.2 [manual] 更新 `docs/handoff.md`:§1 当前状态快照(M2 进度 1/3)/ §2 本次 session 决策(propose+apply)/ §4 下次开工建议(C4 file-upload 起点)/ §5 最近变更历史追加 C3 归档条目

## 9. 总汇

- [x] 9.1 跑 [L1][L2][L3] 全部测试,全绿(L1:76 pass / L2:51 pass / L3:10 pass;C3 新增 72 个用例,无 C2 回归)
