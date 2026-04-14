## Why

围标检测系统(DocumentCheck)第一期的 17 个 capability 级 change 严格串行推进,C1 `infra-base` 是底座 change,所有后续 change(C2 auth、C3~C5 项目/上传/解析、C6~C14 检测、C15~C17 报告/对比/管理)都依赖本 change 提供的 DB、SSE、LLM 适配层、生命周期管理与三层测试脚手架。没有这一层,后续 change 无法独立 propose / apply / archive。

## What Changes

- 后端落地 FastAPI + SQLAlchemy 2.x + Alembic 迁移框架,提供 `/health` 端点(含 DB 连通性检查)
- SSE 推送基础:`/demo/sse` 端点(心跳事件 + 客户端断开自动重连 + 服务端幂等)
- LLM 适配层:统一 Provider 接口,双路配置注入(dashscope / openai),内置超时、限流、降级策略
- 数据生命周期清理定时任务:dry-run 模式仅标记过期文件并输出清单,不真实删除(为后续 C4/C15 做准备)
- 前端基础骨架:Vite + React + TypeScript + 路由 + API client + SSE 客户端封装
- 三层测试脚手架(对齐 CLAUDE.md 测试标准):
  - L1:`backend/tests/unit/`(pytest)+ `frontend/src/**/*.test.tsx`(Vitest + RTL)
  - L2:`backend/tests/e2e/`(pytest + FastAPI TestClient + httpx)
  - L3:项目根 `e2e/`(Playwright + TypeScript,baseURL 默认 `http://localhost:5173`)
- LLM mock 统一入口:`backend/tests/fixtures/llm_mock.py`(后续 8 个 LLM 调用点共享)
- `docker-compose.yml` 一键启动 backend + frontend + postgres
- `.gitignore` 加入 `e2e/artifacts/`(L3 截图/录屏目录)

**范围说明**:
1. 异步任务框架(asyncio + ProcessPoolExecutor)已从 C1 迁出至 C6 `detect-framework`(详见 `docs/execution-plan.md` §3 C1 范围调整说明 + §6 计划变更记录)。理由:C1 阶段无真实消费者(Parser/Detection 都未实现),独立验证困难,避免提前做宽。
2. 仓库预置有 `backend/app/api/routes/{projects,documents,analysis}.py` 占位路由与 `services/parser/analyzer/detector/` 空骨架,属于 C3/C4/C6 范围,**本 change 不纳入验收**,保留现状不动。详细处理见 `design.md` Context "遗留代码处理策略"。

## Capabilities

### New Capabilities

- `infra-base`: 系统基础设施能力,包括 DB 连接与迁移、健康检查、SSE 推送基础、LLM Provider 适配与降级、数据生命周期 dry-run、前端骨架、三层测试脚手架与一键启动编排

### Modified Capabilities

(无 — C1 是首个 change,无既有 spec 可改)

## Impact

- **新增代码**:
  - `backend/app/`:FastAPI 入口、配置、DB 连接、`/health`、`/demo/sse`、LLM 适配层、生命周期任务
  - `backend/alembic/`:迁移框架与初始化迁移
  - `backend/tests/`:`unit/`、`e2e/`、`fixtures/llm_mock.py`、`conftest.py`
  - `frontend/`:Vite + React + TS 项目骨架、路由、API client、SSE hook
  - 项目根 `e2e/`:Playwright 配置、`seed.ts`、`fixtures/`
  - `docker-compose.yml`、`.gitignore` 增量
- **新增依赖**:
  - 后端:`fastapi`、`uvicorn`、`sqlalchemy>=2`、`alembic`、`psycopg`、`httpx`、`pytest`、`pytest-asyncio`、LLM SDK(dashscope / openai)
  - 前端:`react`、`react-router`、`vite`、`vitest`、`@testing-library/react`
  - 项目根:`@playwright/test`、`typescript`、`tsx`(用于 `seed.ts`)
- **API 表面**:`GET /health`、`GET /demo/sse`(均为基础设施级,后续 change 不会修改)
- **DB 表**:本 change 仅建立 alembic 元数据表(`alembic_version`),业务表由后续 change 各自迁移引入
- **配置项**:`DATABASE_URL`、`LLM_PROVIDER`、`LLM_API_KEY`、`LLM_TIMEOUT_S`、`LIFECYCLE_DRY_RUN`(默认 true)
