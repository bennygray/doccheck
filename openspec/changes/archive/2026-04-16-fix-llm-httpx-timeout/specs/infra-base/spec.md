## MODIFIED Requirements

### Requirement: LLM HTTP 客户端 timeout 与配置一致

`OpenAICompatProvider` 的 httpx 请求 timeout SHALL 使用 `self._timeout_s`（来自 `LLM_TIMEOUT_S` 配置），而非 httpx 默认值。

#### Scenario: LLM 响应在配置 timeout 内返回
- **WHEN** LLM 响应在 `LLM_TIMEOUT_S` 秒内返回
- **THEN** 正常返回 LLMResult(text=响应内容)

#### Scenario: LLM 响应超过配置 timeout
- **WHEN** LLM 响应超过 `LLM_TIMEOUT_S` 秒
- **THEN** 返回 LLMResult(error=LLMError(kind="timeout"))，error message 非空且包含超时描述
