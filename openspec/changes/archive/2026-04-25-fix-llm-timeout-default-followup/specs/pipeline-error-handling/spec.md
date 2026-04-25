## MODIFIED Requirements

### Requirement: LLM 调用全局 timeout 安全上限

`backend/app/core/config.py` SHALL 暴露两个独立 timeout 字段:

- `LLM_TIMEOUT_S` → `Settings.llm_timeout_s`(per-call 实际超时,默认 **300 秒**)
- `LLM_CALL_TIMEOUT` → `Settings.llm_call_timeout`(全局 cap,默认 **300 秒**)

`app/services/llm/factory.py` 在构造 `OpenAICompatProvider` 时 SHALL 通过 `_cap_timeout(raw)` 取 `min(raw, llm_call_timeout)` 作为有效 timeout,其中 `raw` 来自 env 路径的 `settings.llm_timeout_s` 或 admin-llm-config DB 路径的 `cfg.timeout_s`。两者并联语义:任一压低 → 实际生效压低;cap 仅当 per-call 配置过大时兜底,不会反向把 per-call 拉高。

默认值同步到 300 的原因(承接 `2026-04-24-config-llm-timeout-default`):前一次 change 只改了 cap 默认值 60→300,但 per-call(`llm_timeout_s`)默认仍是 30,实际生效 = `min(30, 300) = 30`,慢模型(ark-code-latest 类,role_classifier 实测 35~132s,price_rule_detector 实测 ~113s)仍高概率超时。本次把 per-call 默认也对齐到 300,`min(300, 300) = 300`,真正给慢模型留够空间。

部署文件(`backend/.env.example`、`docker-compose.yml`)SHALL 与代码默认值保持同步:`docker-compose.yml::LLM_TIMEOUT_S` 默认值 = `${LLM_TIMEOUT_S:-300}`;`.env.example` 注释 SHALL 显式说明 per-call 与 cap 的并联关系,避免用户误以为只配 cap 即可。

#### Scenario: admin 配置过大 timeout 被 cap

- **WHEN** admin-llm-config 存储的 timeout=1200(秒),LLM_CALL_TIMEOUT=300
- **THEN** 实际 provider 的 `_timeout_s` 取 300(非 1200);provider 层 asyncio.wait_for 仍按 300 生效

#### Scenario: admin 配置小 timeout 保持不变

- **WHEN** admin-llm-config 存储的 timeout=15,LLM_CALL_TIMEOUT=300
- **THEN** 实际 provider 的 `_timeout_s` 取 15

#### Scenario: LLM_CALL_TIMEOUT 可通过 env 覆盖

- **WHEN** 部署环境 `export LLM_CALL_TIMEOUT=60`
- **THEN** `config.llm_call_timeout = 60`,factory 层取 `min(per_call, 60)`

#### Scenario: 未配 env 时 per-call 与 cap 默认值都是 300

- **WHEN** 未设置 `LLM_TIMEOUT_S` 或 `LLM_CALL_TIMEOUT` 环境变量,且 admin-llm-config 未存 timeout
- **THEN** `config.llm_timeout_s = 300.0` 且 `config.llm_call_timeout = 300.0`(均为 code 默认);factory 层 `_cap_timeout(300)` = `min(300, 300)` = 300,provider 层按 300s 生效;ark-code-latest 单次最坏 132s LLM 调用不再超时

#### Scenario: per-call env 压低生效

- **WHEN** 部署环境 `export LLM_TIMEOUT_S=60`,无 LLM_CALL_TIMEOUT env(cap 取代码默认 300)
- **THEN** `config.llm_timeout_s = 60`,factory 层取 `_cap_timeout(60)` = `min(60, 300) = 60`;provider 层按 60s 生效;想要快速失败的部署可主动压低 per-call 而不动 cap
