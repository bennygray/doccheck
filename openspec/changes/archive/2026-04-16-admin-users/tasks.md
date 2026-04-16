## 1. 数据层

- [x] 1.1 [impl] 新建 `backend/app/models/system_config.py` — SystemConfig 模型（id Integer PK, config JSON, updated_by Integer FK nullable, updated_at DateTime）
- [x] 1.2 [impl] 在 `backend/app/models/__init__.py` 注册 SystemConfig
- [x] 1.3 [impl] 生成 Alembic migration（新增 system_configs 表 + insert 默认行 id=1）

## 2. 规则默认值与映射

- [x] 2.1 [impl] 新建 `backend/app/services/admin/rules_defaults.py` — DEFAULT_RULES_CONFIG dict（requirements.md §8 结构）
- [x] 2.2 [impl] 新建 `backend/app/services/admin/rules_mapper.py` — config_to_engine_params() 维度名映射（requirements.md §8 名 → 代码维度名）
- [x] 2.3 [impl] 新建 `backend/app/services/admin/rules_reader.py` — async get_active_rules(session) → dict

## 3. 后端 Schemas

- [x] 3.1 [impl] 新建 `backend/app/schemas/admin.py` — CreateUserRequest / UpdateUserRequest / RulesConfigRequest（含 Pydantic 校验：权重非负、risk_levels 连续、阈值范围、restore_defaults flag）/ RulesConfigResponse

## 4. 后端 Admin 路由

- [x] 4.1 [impl] 新建 `backend/app/api/routes/admin.py` — GET/POST/PATCH /api/admin/users + GET/PUT /api/admin/rules，全部 require_role("admin")
- [x] 4.2 [impl] 在 `backend/app/main.py` 注册 admin router（prefix="/api/admin"）

## 5. 引擎集成

- [x] 5.1 [impl] 修改 `backend/app/services/detect/engine.py` — 检测启动前调用 get_active_rules()，将配置传入 compute_report 和各 agent
- [x] 5.2 [impl] 修改 `backend/app/services/detect/judge.py` — compute_report 接收可选 rules_config，优先用传入的 weights 替代 DIMENSION_WEIGHTS 常量；dimension enabled=false 则跳过

## 6. 前端 API 层

- [x] 6.1 [impl] 在 `frontend/src/services/api.ts` 新增 admin API 函数（getUsers / createUser / updateUser / getRules / updateRules）
- [x] 6.2 [impl] 在 `frontend/src/types/index.ts` 新增 admin 相关类型（AdminUser / RulesConfig / CreateUserPayload / UpdateUserPayload）

## 7. 前端页面

- [x] 7.1 [impl] 新建 `frontend/src/pages/admin/AdminUsersPage.tsx` — 用户表格 + 创建表单 + 启用/禁用开关
- [x] 7.2 [impl] 新建 `frontend/src/pages/admin/AdminRulesPage.tsx` — 规则表单（10 维度 + 全局配置）+ 保存 + 恢复默认
- [x] 7.3 [impl] 修改 `frontend/src/App.tsx` — 新增 /admin/users 和 /admin/rules 路由（AdminRoute 守护）
- [x] 7.4 [impl] 新增 AdminRoute 组件或扩展 ProtectedRoute — role="admin" 校验，非 admin redirect /projects（复用已有 RoleGuard）
- [x] 7.5 [impl] 在导航栏中为 admin 用户显示"管理"入口链接

## 8. L1 后端测试

- [x] 8.1 [L1] admin users API 测试（列表/创建/禁用/self-禁用400/重复用户名409/弱密码422/reviewer 403）— ~7 case
- [x] 8.2 [L1] admin rules API 测试（GET 默认/PUT 合法/PUT 非法权重422/PUT risk_levels 不连续422/restore_defaults/reviewer 403）— ~6 case
- [x] 8.3 [L1] rules_mapper 单元测试（维度名映射正确/缺失字段 fallback/全字段往返一致）— ~3 case

## 9. L1 前端测试

- [x] 9.1 [L1] AdminUsersPage 组件测试（渲染用户列表/创建用户成功/禁用开关/非 admin 重定向）— ~4 case
- [x] 9.2 [L1] AdminRulesPage 组件测试（渲染配置表单/保存成功/恢复默认/校验错误提示）— ~4 case

## 10. L2 E2E 测试

- [x] 10.1 [L2] admin 创建用户→新用户登录→admin 禁用→登录失败 全链路
- [x] 10.2 [L2] admin 修改规则→GET 返回新值→恢复默认→GET 返回默认值
- [x] 10.3 [L2] reviewer 调用 admin API → 全部 403

## 11. L3 手工验证

- [x] 11.1 [L3] 前端 admin 页面 UI 交互验证（创建用户表单/规则表单/保存/恢复默认）— 降级为手工凭证 `e2e/artifacts/c17-2026-04-16/README.md`

## 12. 全量测试

- [x] 12.1 跑 [L1][L2][L3] 全部测试，全绿 — 后端 1025 passed + 前端 92 passed = 1117 全绿
