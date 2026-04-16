## Why

E2E 验收测试中 L-9 LLM 综合研判始终降级（DEF-002）。根因排查：`openai_compat.py` 创建 `httpx.AsyncClient()` 时未传 `timeout`，httpx 默认 read timeout 仅 5s，而 LLM 生成结构化 JSON 响应需 >5s。httpx 先于 `asyncio.wait_for`（30s）触发 `ReadTimeout`，且 `str(ReadTimeout)` 为空字符串导致 error message 不可读。

## What Changes

- `openai_compat.py`：给 `httpx.AsyncClient()` 构造时传入 `timeout=self._timeout_s`，使 httpx read timeout 与业务配置的 `LLM_TIMEOUT_S` 一致
- 同时改进 `httpx.HTTPError` 捕获的 error message，使用 `type(exc).__name__` 兜底避免空字符串

## Capabilities

### New Capabilities

（无新增）

### Modified Capabilities

- `infra-base`: LLM provider 的 httpx timeout 配置修正

## Impact

- **后端代码**: 仅 `backend/app/services/llm/openai_compat.py`（2 行改动）
- **影响面**: 所有 LLM 调用（角色分类/文本相似度/研判等），timeout 行为从 5s 修正为配置值（默认 30s / judge 60s）
