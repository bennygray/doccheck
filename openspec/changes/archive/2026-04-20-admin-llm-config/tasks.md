# admin-llm-config Tasks

## 1. 数据层

- [x] 1.1 [impl] Alembic 0010:data-migration 补 `system_configs.config.llm` 默认值
  - 从代码默认(`dashscope` / 空 key / `qwen-plus` / null base / 30s)写入
  - 向后兼容:已有 SystemConfig 行若已有 `llm` 段则跳过

## 2. Schema + Service

- [x] 2.1 [impl] `schemas/admin.py` 新增 `LLMConfigResponse` / `LLMConfigUpdate` / `LLMTestRequest` / `LLMTestResponse`
  - provider enum:`dashscope` / `openai` / `custom`
  - timeout_s:int 1~300(非整数 float 也接受,cast)
  - api_key 非空校验在 update schema(GET 返脱敏)
- [x] 2.2 [impl] `services/admin/llm_reader.py`:
  - `read_llm_config(db) → LLMConfig dataclass`:DB > env > 默认 三层回退
  - `write_llm_config(db, payload, actor_id)`:写 SystemConfig + 写 audit_log + 调 `invalidate_provider_cache()`
  - `mask_api_key(raw) → "sk-****abc1"`:保留末 4 位,短于 8 位全部脱敏
- [x] 2.3 [impl] 修 `services/llm/factory.py`:
  - 去 `@lru_cache(maxsize=1)`
  - 改成 `_providers: dict[tuple, LLMProvider] = {}`(key = (provider, api_key, model, base_url, timeout))
  - 每次 `get_llm_provider()` 读 `read_llm_config(db)` 获取当前有效配置,按指纹命中 cache 或新建
  - 新增 `invalidate_provider_cache()` 清空 dict
  - 保持旧签名兼容(无 db 参数时回退到 settings env 路径)
- [x] 2.4 [impl] `services/llm/tester.py`:
  - `test_connection(config) → (ok, latency_ms, error_msg)`
  - 发 prompt `"ping"` + `max_tokens=1`,3s 超时;catch 所有异常转成 error_msg

## 3. API 路由

- [x] 3.1 [impl] `routes/admin.py` 扩 3 个 endpoint:
  - `GET /api/admin/llm` → `LLMConfigResponse`(api_key 脱敏)
  - `PUT /api/admin/llm` → 接 `LLMConfigUpdate`,返脱敏 response
  - `POST /api/admin/llm/test` → 接 `LLMTestRequest`(或从 DB 读当前配置),返 `LLMTestResponse`
  - 全部 admin 角色守卫(复用既有 `require_admin` dep)

## 4. 后端测试

- [x] 4.1 [L1] `tests/unit/test_llm_config.py`
  - `mask_api_key` 三种输入(长/短/空)
  - `read_llm_config` 三层 fallback(DB 有 / DB 无+env / env 无+默认)
  - provider schema 验证:非法 provider 拒绝
- [x] 4.2 [L2] `tests/e2e/test_admin_llm.py`
  - `GET /api/admin/llm` admin 通过 + 脱敏 + 非 admin 403
  - `PUT` 更新后 `GET` 返新值脱敏 + audit_log 写入
  - `PUT` 后 factory cache 失效(同一 key 两次调 `get_llm_provider` 返不同实例,若配置改变)
  - `POST /test` mock LLM 返 ok / timeout / 非法 provider
  - 409 / 422 错误路径

## 5. 前端

- [x] 5.1 [impl] `types/index.ts` 增 `LLMConfig` / `LLMConfigUpdate` / `LLMTestResult`
- [x] 5.2 [impl] `services/api.ts` 增 `getLLMConfig / updateLLMConfig / testLLMConnection`
- [x] 5.3 [impl] `pages/admin/AdminLLMPage.tsx`:
  - Breadcrumb + 标题(同 AdminRulesPage 样式)
  - Card:基本配置(provider Select / api_key Password / model / base_url / timeout)
  - Card:测试连接(按钮 + 结果 Alert)
  - 底部操作条:恢复默认 + 保存
  - api_key 占位符显示当前脱敏值,输入即覆盖;空白输入不提交(保持旧值)
- [x] 5.4 [impl] `App.tsx` 挂 `/admin/llm` 路由 + RoleGuard
- [x] 5.5 [impl] `AppLayout.tsx` "管理" 子菜单加 "LLM 配置"

## 6. 前端测试

- [x] 6.1 [L1] `pages/admin/AdminLLMPage.test.tsx`
  - GET 回显脱敏 + 各字段默认值
  - 填入新值 + 保存 → 调用 API
  - 测试连接按钮 loading + 结果展示
  - 空 api_key 提交不传 key(保持旧值契约)

## 7. L3 + 归档

- [x] 7.1 [L3] 手工路径:登录 admin → 进 LLM 配置页 → 改 model → 测试连接 → 保存 → 进某检测详情页启动检测 → 观察 Agent 用新配置调 LLM
  - 如 docker kernel-lock 未解 → 降级为手工截图凭证,放 `e2e/artifacts/admin-llm-<date>/README.md`
- [x] 7.2 [manual] 部署前检查:文档追加"admin-llm 配置优先于 .env;旧 env 不再生效提示"
- [x] 7.3 跑 [L1][L2][L3] 全部测试,全绿
