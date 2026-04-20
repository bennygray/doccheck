# admin-llm Spec

## Purpose

管理员在 Web UI 管理 LLM provider / api_key / model 等运行期配置,无需改 env 或重启服务。

## Requirements

### Req-1: 配置读取的三层回退

The system SHALL resolve LLM config in priority order: DB (`system_configs.config.llm`) > env vars (`settings.llm_*`) > code defaults.

#### Scenario: DB 有完整 llm 段

- **WHEN** `system_configs.id=1` 的 `config.llm = {"provider": "openai", "api_key": "sk-xxx", ...}`
- **THEN** `read_llm_config(db)` returns `LLMConfig(provider="openai", api_key="sk-xxx", ...)` with `source="db"`

#### Scenario: DB 无 llm 段,env 有

- **WHEN** `system_configs.config` 不含 `llm` 键,`settings.llm_provider="dashscope"`
- **THEN** `read_llm_config(db)` returns env 值 with `source="env"`

#### Scenario: DB 无 env 空,走代码默认

- **WHEN** DB 无 llm,`settings.llm_api_key=""`
- **THEN** `read_llm_config` returns 代码默认(`dashscope / "" / qwen-plus / None / 30.0`) with `source="default"`

### Req-2: api_key 脱敏回显

All read operations (GET, after PUT response) SHALL return `api_key` with only last 4 chars visible as `sk-****xxxx`. Raw key MUST NEVER leak to frontend.

#### Scenario: 正常 key

- **WHEN** `api_key = "sk-abcdef1234"`
- **THEN** response `api_key_masked = "sk-****1234"`

#### Scenario: 短 key(< 8 字符)

- **WHEN** `api_key = "abc"`
- **THEN** response `api_key_masked = "sk-****"`(固定占位,不暴露长度)

#### Scenario: 空 key

- **WHEN** `api_key = ""` or `None`
- **THEN** response `api_key_masked = ""`(完全为空,提示前端需要配置)

### Req-3: 更新配置 + 缓存失效

The `PUT /api/admin/llm` endpoint SHALL persist to DB, invalidate factory provider cache, write audit log.

#### Scenario: admin 更新 provider

- **WHEN** admin `PUT /api/admin/llm` with `{"provider": "openai", "model": "gpt-4o-mini", ...}`
- **THEN** response 200 with 脱敏回显
- **AND** `system_configs.config.llm` 更新
- **AND** `_providers` dict cleared
- **AND** `audit_logs` 写一条 `action="admin.llm.update"` 记录,before/after 均脱敏

#### Scenario: admin 提交空 api_key

- **WHEN** `PUT` 的 `api_key=""` 或字段缺失
- **THEN** 后端保持旧 api_key 不变(回显脱敏值)
- **AND** 其他字段照常更新

### Req-4: 测试连接

The `POST /api/admin/llm/test` endpoint SHALL send a minimum-cost probe to verify provider+key, return `{ok, latency_ms, error}`.

#### Scenario: 连接成功

- **WHEN** admin 调 `POST /api/admin/llm/test` with valid config
- **THEN** LLM 返 200,endpoint 返 `{ok: true, latency_ms: <int>, error: null}`

#### Scenario: api_key 无效

- **WHEN** LLM 返 401
- **THEN** endpoint 返 `{ok: false, latency_ms: <int>, error: "401 Unauthorized"}`

#### Scenario: provider 超时

- **WHEN** 10s 内未返回
- **THEN** endpoint 返 `{ok: false, error: "timeout after 10s"}`

### Req-5: 权限隔离

All `/api/admin/llm*` endpoints SHALL require admin role. Non-admin MUST receive 403.

#### Scenario: 非 admin 访问

- **WHEN** reviewer 角色调 `GET /api/admin/llm`
- **THEN** 返 403 Forbidden

### Req-6: 前端 UI

The `AdminLLMPage` SHALL provide provider select, key input (masked), model/base_url text, timeout number, test button, save, and restore defaults.

#### Scenario: 页面加载回显

- **WHEN** admin 访问 `/admin/llm`
- **THEN** 各字段预填 GET 结果值;api_key 输入框 placeholder = 当前脱敏值

#### Scenario: 保存时 api_key 空白保持旧值

- **WHEN** admin 未改 api_key 就点"保存"
- **THEN** 前端 `updateLLMConfig` payload 不含 api_key 字段(或传空字符串)
- **AND** 后端检测到空 api_key → 保持旧值

#### Scenario: 测试连接按钮

- **WHEN** admin 改 provider 后点 "测试连接"
- **THEN** 前端调 `testLLMConnection(current_form_values)`
- **AND** 展示 ok/失败 Alert + latency

#### Scenario: 非 admin 访问页面

- **WHEN** reviewer 访问 `/admin/llm`
- **THEN** RoleGuard 拦截 → 重定向到 `/projects`
