## Why

部分 API 路径不带尾部 `/` 时返回 307 Temporary Redirect（如 `POST /api/projects` → 307 → `/api/projects/`），增加不必要的网络往返，且部分 HTTP 客户端默认不跟随 redirect 导致请求失败（DEF-005）。

## What Changes

- 在 `FastAPI()` 构造时设置 `redirect_slashes=False`，禁用自动重定向

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 spec 级变更，仅基础设施配置调整）

## Impact

- **后端代码**: 仅 `backend/app/main.py` 一行参数
- **行为变化**: 不带尾部 `/` 的请求直接匹配路由，不再 307 重定向
