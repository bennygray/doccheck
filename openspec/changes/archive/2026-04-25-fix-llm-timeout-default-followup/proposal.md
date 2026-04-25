## Why

archive change `2026-04-24-config-llm-timeout-default` 把 `Settings.llm_call_timeout`(全局 cap)默认值从 60→300,本意是给 `ark-code-latest` 类慢模型预留空间(role_classifier 实测 35~132s,price_rule_detector 实测 ~113s)。但**改完后实际部署零行为变化**:

- factory.py [`_cap_timeout`](backend/app/services/llm/factory.py#L37) 实际生效路径是 `min(per_call_timeout, cap)`;两个值并联走 `min`
- per-call 字段 `Settings.llm_timeout_s` 默认仍是 30,**那次 change 没动**
- `backend/.env`(`LLM_TIMEOUT_S=60`)和 `docker-compose.yml`(`${LLM_TIMEOUT_S:-30}`)也没同步
- 实际生效 = `min(60, 300) = 60` —— 改 cap 等于不改

2026-04-25 用 3 个真实供应商 zip(投标文件模板 2 系列,投标人 2778/2779/2780)再次 E2E 验证暴露此问题:price_rule_detector 60s 超时 → `price_parsing_rules.status='failed'` → 3 个 bidder 全 `price_failed` → 报价相关 3 维度被检测引擎跳过(报价一致性 / 报价异常 / 报价接近限价)→ 综合分被稀释。证据:[backend.log](e2e/artifacts/manual-run-2026-04-25/backend.log) 第 6409 行单条 LLM error: `kind=timeout msg=LLM 调用超时(>60.0s)`。

本 change 把 archive 那次漏的同步迁移补齐 ——**让 per-call 默认值与 cap 对齐(均 300)**,且现有部署文件(docker-compose / .env)不再锁老值。

## What Changes

- `backend/app/core/config.py::Settings.llm_timeout_s` 默认 `30.0` → `300.0`,docstring 解释与 cap 关系(per-call 与 cap 现在共用 300,真要快失败请 admin/llm UI 配)
- `backend/.env.example` 修订注释:讲清 `LLM_TIMEOUT_S` 与 `LLM_CALL_TIMEOUT` 的并联关系,明确 per-call 才是实际生效值
- `docker-compose.yml::LLM_TIMEOUT_S` 默认值 `30` → `300`(与代码默认对齐)
- `backend/.env`(本机)删 `LLM_TIMEOUT_S=60` 这一行,让代码默认生效
- `backend/tests/unit/test_llm_timeout_default.py` 加一条 `llm_timeout_s == 300.0`(原有的 `llm_call_timeout` 测试保留)

**不改**:`_cap_timeout` 逻辑、admin-llm-config UI/DB、各 Agent 自有 timeout(`ERROR_CONSISTENCY_LLM_TIMEOUT_S` / `STYLE_LLM_TIMEOUT_S` 用独立前缀,不受全局默认影响)、env 覆盖能力(`LLM_TIMEOUT_S=N` 仍可压低)

本 change 与前一个一样属 **CLAUDE.md "孤立改配置"例外**:仅改默认值与部署文件同步,无 [L2]/[L3] 业务流测试;保留 1 条 [L1] 钉默认值,1 条 [manual] 重跑 e2e 项目 2486 验证报价回填恢复。

## Capabilities

### New Capabilities
(无)

### Modified Capabilities
- `pipeline-error-handling`: Requirement "LLM 调用全局 timeout 安全上限" 改名为 "LLM 调用全局 timeout 与 per-call 默认值",描述把 per-call 默认值与 cap 对齐到 300 的语义,新增 1 个 scenario 锁住 `llm_timeout_s` 默认 300

## Impact

- 代码:1 行(config.py 默认值)+ docstring
- 部署文件:.env.example 注释、docker-compose.yml 默认值、本机 .env 删 1 行(共 3 文件)
- 测试:test_llm_timeout_default.py 加 1 case
- Spec:1 delta 修改 pipeline-error-handling 的既有 Requirement
- 行为:已用 env `LLM_TIMEOUT_S=N` 显式配置的部署**零影响**(env 仍优先);未显式配的部署默认从 30/60s 提升到 300s,与上次 archive 已经接受的"慢失败 4 分钟"代价一致
- 凭证:本次 e2e re-parse 跑通后,`e2e/artifacts/fix-llm-timeout-default-followup-2026-04-26/` 存 bidder parse_status / price_parsing_rule.status / 维度得分对比截图
