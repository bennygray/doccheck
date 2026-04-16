## Context

FastAPI 默认 `redirect_slashes=True`，当路由定义为 `/api/projects/` 而请求为 `/api/projects` 时自动 307 重定向。

## Goals / Non-Goals

**Goals:**
- 消除 307 重定向，请求直接匹配

**Non-Goals:**
- 不统一路由定义风格（带/不带尾部斜杠均可匹配）

## Decisions

### D1: `redirect_slashes=False`

最小改动，一行参数。FastAPI 底层 Starlette 的 Router 会同时匹配带和不带尾部斜杠的路径。
