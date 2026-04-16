## Why

M4 最后一个 change。系统已具备完整检测→报告→导出→对比能力，但缺少用户管理和检测规则配置——管理员无法新增审查员账号，也无法调整维度权重/阈值以适应不同业务场景。C17 补齐 US-8.1~8.3 + US-9.1，使系统达到可交付状态（M4 判据）。

## What Changes

- 新增 `/api/admin/users` CRUD 路由（列表/创建/启用禁用），仅 admin 角色可调用
- 新增 `/api/admin/rules` GET/PUT 路由，读写全局检测规则配置（SystemConfig 单行 JSON）
- 新增 `SystemConfig` 数据库模型（单行存储，PUT 覆盖写入，支持"恢复默认"）
- 新增前端 `/admin/users` 页面（用户列表+创建表单+启用禁用开关）
- 新增前端 `/admin/rules` 页面（最简表单：10 维度 enabled/weight/llm_enabled + 特有阈值 + 全局配置 + 恢复默认按钮）
- 检测引擎启动时读取 SystemConfig → 映射到各 agent env var，替代硬编码默认值

## Capabilities

### New Capabilities
- `admin-users`: 管理员用户 CRUD（列表/创建/启用禁用）— 后端 API + 前端页面
- `admin-rules`: 全局检测规则配置（维度权重/阈值/开关 + 全局参数）— 后端 API + 前端页面 + 引擎集成

### Modified Capabilities
（无 spec 级行为变更，检测引擎内部读取配置源从 env var 改为 DB，不影响外部接口）

## Impact

- **后端新增**：`models/system_config.py`、`routes/admin.py`（或拆 `admin_users.py` + `admin_rules.py`）、`schemas/admin.py`
- **后端修改**：`main.py`（注册 admin router）、`services/detect/judge.py`（DIMENSION_WEIGHTS 从 SystemConfig 读取）、各 agent config.py（阈值从 SystemConfig 读取）
- **前端新增**：`pages/AdminUsersPage.tsx`、`pages/AdminRulesPage.tsx`、`services/api.ts`（新增 admin API 函数）、`App.tsx`（新增路由）
- **数据库**：新增 `system_configs` 表（Alembic migration）
- **不动**：C6~C16 检测层/导出层/对比层逻辑不变，仅配置读取源变化
