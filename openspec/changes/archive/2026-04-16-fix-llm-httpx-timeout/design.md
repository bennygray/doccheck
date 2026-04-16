## Context

`openai_compat.py` 用双层 timeout 设计：外层 `asyncio.wait_for(timeout=self._timeout_s)` + 内层 httpx 默认 5s。外层永远触发不了，因为内层先超时。

## Goals / Non-Goals

**Goals:**
- httpx read timeout = `self._timeout_s`（与 `LLM_TIMEOUT_S` 配置一致）
- error message 不为空字符串

**Non-Goals:**
- 不改 timeout 架构（保留 asyncio.wait_for 作为兜底）

## Decisions

### D1: 传 `httpx.Timeout(self._timeout_s)` 到 AsyncClient

httpx 的 `timeout` 参数同时控制 connect / read / write / pool timeout。传单个 float 统一设为同一值，与 `asyncio.wait_for` 的 timeout 保持一致。

### D2: error message 用 `f"{type(exc).__name__}: {exc}"` 格式

`httpx.ReadTimeout` 的 `str()` 为空，改为带类名前缀确保可读。
