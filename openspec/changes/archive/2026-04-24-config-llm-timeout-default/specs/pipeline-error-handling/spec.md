## MODIFIED Requirements

### Requirement: LLM 调用全局 timeout 安全上限

`backend/app/core/config.py` SHALL 暴露 `LLM_CALL_TIMEOUT`(默认 **300 秒**);`app/services/llm/factory.py` 从 admin-llm-config 读 timeout 时 SHALL 取 `min(admin_timeout, LLM_CALL_TIMEOUT)` 作为有效 timeout,传给 `OpenAICompatProvider`。admin 层 UI 无需改动,该上限仅在 factory 层防御。

默认值从 60 秒提升到 300 秒的原因:ark-code-latest / gpt-4 类慢模型在中文长 prompt(role_classifier 批量分类 / price_rule_detector 表结构识别)场景下实测单次调用耗时 35~132 秒,60 秒 cap 高概率触发 timeout → 回退关键词兜底 → 假阳性放大。

#### Scenario: admin 配置过大 timeout 被 cap
- **WHEN** admin-llm-config 存储的 timeout=1200(秒),LLM_CALL_TIMEOUT=300
- **THEN** 实际 provider 的 `_timeout_s` 取 300(非 1200);provider 层 asyncio.wait_for 仍按 300 生效

#### Scenario: admin 配置小 timeout 保持不变
- **WHEN** admin-llm-config 存储的 timeout=15,LLM_CALL_TIMEOUT=300
- **THEN** 实际 provider 的 `_timeout_s` 取 15

#### Scenario: LLM_CALL_TIMEOUT 可通过 env 覆盖
- **WHEN** 部署环境 `export LLM_CALL_TIMEOUT=60`
- **THEN** `config.llm_call_timeout = 60`,factory 层取 `min(admin_timeout, 60)`

#### Scenario: 未配置 env 时取 code 默认值
- **WHEN** 未设置 `LLM_CALL_TIMEOUT` 环境变量且 admin-llm-config 未存 timeout
- **THEN** `config.llm_call_timeout = 300.0`(code 默认),factory 层生效 cap=300

## ADDED Requirements

### Requirement: Windows 控制台日志 UTF-8 兜底

`backend/app/main.py` lifespan 在启动初段(tracker 注册前)SHALL 尝试对 `sys.stdout` / `sys.stderr` 执行 `reconfigure(encoding="utf-8", errors="replace")`;AttributeError / ValueError 场景下静默跳过(test client / 容器化部署等 stream 已被替换的场景不报错)。

此契约防御 Windows 默认 GBK 控制台对含 `U+00BA` 等冷门 Unicode 字符的中文日志触发 `UnicodeEncodeError` 导致 logging emit 崩溃(2026-04-24 E2E 验证实测)。

#### Scenario: Windows GBK 控制台启动
- **WHEN** `uvicorn` 在 Windows 默认 cmd / PowerShell(GBK 编码)启动
- **THEN** lifespan 顶部成功 reconfigure stdout/stderr 为 utf-8;后续 logger 输出含 `U+00BA` 等罕见字符不再 crash

#### Scenario: stdout 已被测试框架替换
- **WHEN** pytest 的 capsys / caplog 已把 sys.stdout 替换为 StringIO 或 CaptureIO
- **THEN** `sys.stdout.reconfigure` 调用触发 AttributeError(StringIO 无 reconfigure),try/except 兜底吞异常,lifespan 继续启动不中断
