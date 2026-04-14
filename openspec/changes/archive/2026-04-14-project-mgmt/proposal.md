## Why

M1 已完成(C1 infra-base + C2 auth),系统具备登录与路由守卫能力,但 `/projects` 目前仅是占位页。C3 是 M2 的第一块基石——没有项目实体,后续 C4(投标人与文件上传)、C5(解析)、C6+(检测)都无处挂载。本 change 完成项目的基础 CRUD、权限隔离与列表筛选搜索,使审查员可以进入真实的项目生命周期。

## What Changes

- **新增** `Project` 数据模型与 alembic 迁移(`0002_projects`):包含 `name / bid_code / max_price / description / status / risk_level / owner_id / created_at / updated_at / deleted_at`
- **改造** `backend/app/api/routes/projects.py`(C1 保留的占位骨架):实现 `POST / GET(list) / GET(detail) / DELETE` 四个端点,全部挂 `Depends(get_current_user)`
- **新增** 角色隔离逻辑:reviewer 仅见/改/删自己的项目(`owner_id == current_user.id`);admin 可见所有项目
- **新增** 列表分页(`page / size`,默认 size=12)、状态筛选(`status`)、风险等级筛选(`risk_level`)、关键词搜索(`search`,匹配 `name` 与 `bid_code`)
- **新增** 软删除语义:`DELETE /{id}` 置 `deleted_at=now()`,所有查询统一过滤 `deleted_at IS NULL`;已软删项目按 404 返回
- **新增** 删除前状态保护:`status == 'analyzing'` 时返回 409(C3 阶段实际无法产生该状态,但代码前置挂上,给 C6 留接口)
- **前端替换** `ProjectsPlaceholderPage` → `ProjectListPage`(真实列表 + 筛选 + 搜索 + 分页);**新增** `ProjectCreatePage`(`/projects/new`)与 `ProjectDetailPage`(`/projects/:id`,基本信息 + bidder/file/progress 占位区,预留给 C4+)
- **扩展** `frontend/src/services/api.ts`:新增 `listProjects / createProject / getProject / deleteProject` 四个方法,复用 C2 已建立的 Authorization 头注入 + 401 回调骨架
- **文档联动**:归档时同步修订 `docs/user-stories.md` US-2.4 AC-3(硬删→软删),与本 change 的删除语义对齐

## Capabilities

### New Capabilities

- `project-mgmt`: 检测项目的创建、查询(列表/详情,含分页/筛选/搜索)、软删除,以及基于角色的数据隔离

### Modified Capabilities

(无。`auth` spec 的鉴权能力本 change 仅消费不修改;`infra-base` 仅消费其 DB/迁移框架。)

## Impact

- **受影响代码**
  - 后端:新增 `backend/app/models/project.py`、`backend/app/schemas/project.py`;改造 `backend/app/api/routes/projects.py`;新增 `backend/alembic/versions/0002_projects.py`
  - 前端:替换 `frontend/src/pages/ProjectsPlaceholderPage.tsx`;新增 `frontend/src/pages/projects/{ProjectListPage,ProjectCreatePage,ProjectDetailPage}.tsx`;扩展 `frontend/src/services/api.ts` 与 `frontend/src/types/index.ts`;更新 `frontend/src/App.tsx` 路由表
  - 测试:新增 `backend/tests/unit/test_project_schema.py`、`backend/tests/e2e/test_projects_api.py`;新增 `e2e/tests/c3-project-crud.spec.ts`
- **受影响 API**
  - `GET /api/projects/` → 实装 分页/筛选/搜索/权限过滤
  - `POST /api/projects/` → 实装 创建
  - `GET /api/projects/{id}` → 新增 详情
  - `DELETE /api/projects/{id}` → 新增 软删除
- **依赖**
  - 上游依赖(已就绪):C1 DB/迁移框架、C2 `get_current_user` / `require_role` / `User` 模型
  - 下游预留:C4 会给 `projects` 加反向关联 `bidders`;C6 会把 `status` 推进到 `parsing/analyzing/completed` 并填充 `risk_level`
- **不涉及**
  - 不引入状态机库(status 用 VARCHAR + 应用层枚举)
  - 不做乐观锁/版本号(无并发写冲突场景)
  - 不提供软删恢复接口(延到 C17 admin-users)
  - 不清理任何磁盘文件(C3 阶段项目尚未关联任何物理文件;软删项目的文件清理由 C1 数据生命周期任务统一处理,C4 上线后落地)
