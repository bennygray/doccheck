## Why

C1 infra-base 定了 LLM Provider 工厂模式(`backend/app/services/llm/factory.py`),配置从环境变量读、启动时 `@lru_cache` 建单例,运行期**不可变**。管理员要换 provider / 换 key / 调 timeout 都得改 `.env` + 重启服务,既不便利也不安全(生产 env 通常运维持有,业务管理员拿不到)。

C17 admin-rules 已铺好"后台可配置"的基础设施(`SystemConfig` 单行 JSON 表 + `/api/admin/rules` GET/PUT 路由 + `AdminRulesPage` 前端),本 change 沿用同一套底座,新增 LLM 配置维度,让管理员在 Web UI 完成:

- 切换 provider(dashscope / openai / custom 兼容端点)
- 更新 api_key(脱敏回显,只露末 4 位)
- 改 model / base_url / timeout
- **测试连接**按钮验证配置正确性
- 保存即时生效,无需重启服务

并与现有 `settings` env 配置保持三层优先级兼容(DB > env > 默认值),已部署实例的旧 env 不用动。

## What Changes

### 数据层
- **复用 `system_configs.config` JSON**,不新建表;在 JSON 顶层增 `llm` 子段,结构:
  ```json
  {
    "llm": {
      "provider": "dashscope",
      "api_key": "sk-xxx...",
      "model": "qwen-plus",
      "base_url": null,
      "timeout_s": 30
    },
    "dimensions": {...},
    "risk_levels": {...}
  }
  ```
- Alembic 0010:给已存在的 SystemConfig 行补默认 `llm` 子段(从 env 或代码默认值拷过来,避免首次启动空值)

### API 层
- `GET /api/admin/llm` → 返 `LLMConfigResponse`,api_key 脱敏为 `sk-****abc1` 格式(保留末 4 位)
- `PUT /api/admin/llm` → 接 `LLMConfigUpdate`,写入 DB,失效 factory 缓存,写 audit_log
- `POST /api/admin/llm/test` → 发一个 low-cost 请求验证 provider/key/base_url,返 `{ok: bool, latency_ms: int, error?: str}`
- 三 endpoint 全 admin 角色守卫

### Service 层
- 新 `services/admin/llm_reader.py`:从 SystemConfig 读 LLM 配置;DB 无值 → 回退 `settings`(env) → 再回退代码默认;脱敏函数 `mask_api_key()`
- **修 `services/llm/factory.py`**:去掉 `@lru_cache(maxsize=1)`,改用"配置指纹哈希作为 cache key"的字典缓存;PUT 后调 `invalidate_provider_cache()` 清空
- 新 `services/llm/tester.py`:`test_connection()` 函数,用临时 provider 实例发极短 prompt(eg. `"hi"`,max_tokens=1)

### 前端
- 新 `AdminLLMPage.tsx`:provider Select / api_key Input.Password / model / base_url / timeout InputNumber / 测试连接按钮 / 保存 / 恢复默认
- `App.tsx` 注册 `/admin/llm` + RoleGuard
- `AppLayout.tsx` 侧栏"管理"子菜单加"LLM 配置"
- `services/api.ts` 增 `getLLMConfig / updateLLMConfig / testLLMConnection`

### 文档
- 新 `openspec/specs/admin-llm/spec.md`(6 Req / 14 Scenario)
- `docs/design-language.md` 不动(已有 antd Form 规范可复用)
- `docs/handoff.md` 归档追加

## Impact

- Affected specs: **新增 admin-llm**;现有 admin-rules / admin-users 不动
- Affected code:
  - backend: `schemas/admin.py` / `services/admin/llm_reader.py`(新) / `services/llm/factory.py`(改) / `services/llm/tester.py`(新) / `routes/admin.py`(扩) / alembic 0010
  - frontend: `pages/admin/AdminLLMPage.tsx`(新) / `App.tsx` / `AppLayout.tsx` / `services/api.ts` / `types/index.ts`
- Breaking changes: **无**。现有 LLM 调用链路(11 Agent + judge + pipeline)完全不知情;factory 签名 `get_llm_provider()` 不变。
- Env 回退保证兼容:部署里若 DB 无 llm 段(新部署)自动读 `settings.llm_*`,零迁移成本。
