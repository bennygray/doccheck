## Context

M4 最后一个 change（C17）。系统已有完整 User 模型（10 字段，C2）+ auth 路由（login/logout/me/change-password）+ `require_role("admin")` 依赖。后端无 admin 路由（GAP-12）。检测引擎 11 维度权重硬编码在 `judge.py` DIMENSION_WEIGHTS，~50 个 agent 阈值通过 env var 读取。

用户已敲定 4 项产品决策：
- Q1: 仅全局级配置（单行 SystemConfig）
- Q2: 仅最新值 + 恢复默认（不做版本号）
- Q3: 仅 admin 手动创建用户（无自注册）
- Q4: 规则范围按 requirements.md §8 最小集

## Goals / Non-Goals

**Goals:**
- 管理员可 CRUD 用户（列表/创建/启用禁用）
- 管理员可读写全局检测规则配置（维度开关/权重/阈值 + 全局参数）
- 检测引擎运行时从 SystemConfig 读取配置，替代硬编码/env var 默认值
- 禁用用户后其 JWT 立即失效（已有机制：`get_current_user` 查 `is_active`）

**Non-Goals:**
- 项目级规则覆盖（仅全局）
- 规则版本号 / 历史回滚（仅恢复默认）
- 用户自注册
- LLM 配置管理（第二期 US-10）
- 按维度分 Tab 的完整配置 UI（第二期 US-9.1 备注）
- 暴露全部 ~50 个 agent env var（最小集）

## Decisions

### D1: SystemConfig 模型设计

单表 `system_configs`，单行存储（id=1），字段：`id` (Integer PK), `config` (JSON), `updated_by` (Integer FK → users.id, nullable), `updated_at` (DateTime)。

应用启动时（lifespan）如果表空则 insert 默认配置行。PUT 时覆盖 `config` 字段。"恢复默认"= PUT 时 body 为空或带 `restore_defaults=true` flag → 后端用代码内置 `DEFAULT_RULES_CONFIG` dict 覆盖。

**替代方案**：UUID 主键（requirements.md 原设计）→ 不采用，Integer 更简单，单行不需要 UUID。

### D2: DEFAULT_RULES_CONFIG 常量位置

定义在 `backend/app/services/admin/rules_defaults.py`，包含 requirements.md §8 完整 JSON 结构。这是恢复默认的唯一真相源。

代码中的 DIMENSION_WEIGHTS（judge.py）和各 agent config.py 的 env var 默认值保持不动——它们是"检测引擎自身的 fallback"。SystemConfig 存在且有值时优先读 SystemConfig；SystemConfig 缺失或字段缺失时 fallback 到代码默认值。

### D3: requirements.md 维度名 → 实际 agent 维度名映射

requirements.md §8 用的维度名（10 个）与实际代码维度名（11 个）不一致。SystemConfig JSON 面向用户，使用 requirements.md §8 的维度名。引擎读取时通过映射表转换：

```
requirements.md §8 名          → 代码维度名
hardware_fingerprint           → metadata_machine
error_consistency              → error_consistency
text_similarity                → text_similarity
price_similarity               → price_consistency
image_reuse                    → image_reuse
language_style                 → style
software_metadata              → metadata_author (+ metadata_time 共享 enabled/llm_enabled)
pricing_pattern                → section_similarity
price_ceiling                  → price_anomaly
operation_time                 → metadata_time (共享 enabled;独有阈值 window_minutes)
```

注意 `structure_similarity` 在 requirements.md 中不直接暴露（合入 pricing_pattern），`metadata_author` 和 `metadata_time` 共享 `software_metadata` 和 `operation_time` 的开关。

映射逻辑放在 `services/admin/rules_mapper.py`，提供 `config_to_engine_params(config: dict) -> dict` 函数。

### D4: 引擎集成方式

新增 `services/admin/rules_reader.py`，提供 `async get_active_rules(session) -> dict`：查 SystemConfig 单行 → 若无则返回 DEFAULT_RULES_CONFIG。

`judge.py` 的 `compute_report` 接收一个可选 `rules_config: dict | None` 参数。engine.py 在启动检测前调用 `get_active_rules()` 取配置，传入 `compute_report`。compute_report 内部用传入的 weights 替代 DIMENSION_WEIGHTS 常量。

各 agent config.py 的 env var 读取保持不变（作为 fallback）。引擎层面在调用 agent 前，将 SystemConfig 中的对应阈值写入 agent 的 config（或 context dict），agent 优先读 context 中的值。

**替代方案**：在 agent 内部直接查 DB → 不采用，agent 不应有 DB 依赖；且会导致 N 个 agent 各自查一次。

### D5: Admin 路由结构

单文件 `routes/admin.py`，包含两组 endpoint：

用户管理：
- `GET /api/admin/users` → 列表，返回 `UserPublic[]`
- `POST /api/admin/users` → 创建，入参 `{username, password, role}`，返回 `UserPublic`
- `PATCH /api/admin/users/{id}` → 修改 `is_active` / `role`，返回 `UserPublic`

规则配置：
- `GET /api/admin/rules` → 返回当前配置 JSON
- `PUT /api/admin/rules` → 覆盖更新，入参完整配置 JSON 或 `{restore_defaults: true}`

所有 endpoint 使用 `Depends(require_role("admin"))` 守护。

### D6: 规则校验

PUT `/api/admin/rules` 使用 Pydantic model 校验入参：
- 维度 weight 非负
- risk_levels.high > risk_levels.medium > 0，且 high ≤ 100
- enabled / llm_enabled 为 bool
- 各维度特有阈值有合理范围（如 threshold 0~100，window_minutes > 0）
- metadata_whitelist 为 string 数组
- file_retention_days > 0

校验失败 → 422。

### D7: 禁用用户 JWT 立即失效

已有机制：`get_current_user` 每次请求查 DB `user.is_active`，false → 403。无需额外实现。admin 不能禁用自己（`PATCH` 时 `user_id == current_user.id` 且 `is_active=false` → 400）。

### D8: 前端页面

两个新页面，挂在 `/admin/users` 和 `/admin/rules`，仅 admin 角色可访问（前端路由守护 + 导航栏只对 admin 显示管理入口）。

`AdminUsersPage`：
- 用户表格（username / role / is_active / created_at）
- "创建用户"按钮 → 弹出表单（username / password / role 下拉）
- 每行有"启用/禁用"开关

`AdminRulesPage`：
- 最简表单（不按维度分 Tab）：10 维度各一组字段（enabled checkbox / weight number / llm_enabled checkbox / 特有阈值 number）
- 全局配置区（risk_levels / keywords textarea / whitelist textarea / min_paragraph_length / file_retention_days）
- "保存"按钮 + "恢复默认"按钮
- 加载时 GET 填充，保存时 PUT 提交

### D9: Alembic Migration

新增 `system_configs` 表。Migration 中 insert 默认行（id=1, config=DEFAULT_RULES_CONFIG JSON, updated_by=NULL）。

### D10: 前端 admin 路由守护

ProtectedRoute 组件已有，但只检查登录状态。新增 `AdminRoute` 组件（或在 ProtectedRoute 加 `requireRole` prop）：检查 `user.role === "admin"`，非 admin → redirect `/projects`。

### D11: 密码创建复用

admin 创建用户时的密码规则复用 `ChangePasswordRequest` 的校验逻辑（≥8 位 + 字母 + 数字）。后端 `CreateUserRequest` schema 使用相同 validator。新用户默认 `must_change_password=true`。

### D12: 测试计划

- L1 后端：admin users CRUD (6) + admin rules GET/PUT/restore/validation (6) + rules_mapper (3) = ~15
- L1 前端：AdminUsersPage (4) + AdminRulesPage (4) = ~8
- L2 E2E：admin 创建用户→登录→禁用→登录失败 (1) + 修改规则→检测生效 (1) + 恢复默认 (1) = 3
- L3 手工：UI 表单交互验证

## Risks / Trade-offs

- **[Risk] requirements.md 维度名与代码维度名不一致** → D3 映射表兜底；映射逻辑有单元测试覆盖
- **[Risk] SystemConfig 单行并发写** → 第一期 admin 只有一人，忽略；若需要则加 `SELECT FOR UPDATE`
- **[Risk] 修改规则后已运行的检测不受影响** → 预期行为：规则只影响下次检测。已运行的报告保持不变
- **[Trade-off] 不暴露全部 ~50 个 agent 参数** → 接受：第一期最小集满足 US-9.1；二期按需扩展
- **[Trade-off] 不做规则版本号** → 接受："恢复默认"覆盖最常见回滚场景；audit_log 已记录 PUT 操作（C15 AuditLog 可扩展记录规则变更）
