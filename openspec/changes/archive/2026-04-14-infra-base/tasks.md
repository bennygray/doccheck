## 1. 后端基础

- [x] 1.1 `[impl]` 初始化 `backend/` uv 工程,`pyproject.toml` 声明依赖(fastapi、uvicorn、sqlalchemy>=2、alembic、psycopg[binary]、httpx、pydantic-settings、python-dotenv、apscheduler 或由 D4 Open Question 决议是否替换为 asyncio 轻量方案)
- [x] 1.2 `[impl]` 建立 `backend/app/core/config.py`(pydantic-settings,读取 `DATABASE_URL`/`LLM_PROVIDER`/`LLM_API_KEY`/`LLM_TIMEOUT_S`/`LIFECYCLE_DRY_RUN`/`LIFECYCLE_INTERVAL_S`/`LIFECYCLE_AGE_DAYS`)
- [x] 1.3 `[impl]` 建立 `backend/app/db/session.py`(SQLAlchemy 2.x engine+session,含断连自动重连 pool_pre_ping)
- [x] 1.4 `[impl]` alembic 初始化(手写 `alembic.ini` + `alembic/env.py`,async 模板,`sqlalchemy.url` 从 app.core.config 注入)
- [x] 1.5 `[impl]` 实现 `GET /api/health` 路由:返回 `{"status","db"}`,DB 不通返回 503(见 spec Requirement 健康检查端点)
- [x] 1.6 `[impl]` `backend/app/main.py` FastAPI 入口,挂载 health 路由,CORS 允许 `http://localhost:5173`

## 2. SSE 推送基础

- [x] 2.1 `[impl]` 实现 `GET /demo/sse`:`StreamingResponse` + 异步生成器,每 `HEARTBEAT_INTERVAL_S` 秒推一次 `event: heartbeat`,客户端断开由 `asyncio.CancelledError` 检测(ASGITransport 测试环境 `is_disconnected()` 会误报,已去除)
- [x] 2.2 `[impl]` 在 `backend/app/api/routes/` 组织路由模块并注册到 main

## 3. LLM 适配层

- [x] 3.1 `[impl]` `backend/app/services/llm/base.py`:定义 `LLMProvider` Protocol、`LLMResult`、`LLMError(kind, message, ...)` dataclass
- [x] 3.2 `[impl]` `backend/app/services/llm/openai_compat.py`:统一 OpenAI 兼容 Provider(dashscope 与 openai 仅 base_url 不同,压成一个实现避免过度设计;原 tasks 写的"dashscope_provider.py + openai_provider.py"合并为本文件 + factory 按 provider 选 base_url)
- [x] 3.3 `[impl]` 在适配层内实现统一超时(`asyncio.wait_for(..., LLM_TIMEOUT_S)`)与限流识别(捕获 429 → `LLMError(kind="rate_limit")`),**不**做自动 fallback
- [x] 3.4 `[impl]` 提供 `get_llm_provider()` 工厂函数(`backend/app/services/llm/factory.py`),供路由/服务注入

## 4. 数据生命周期 dry-run

- [x] 4.1 `[impl]` `backend/app/services/lifecycle/cleanup.py`:定义 `scan_expired(root, age_days) -> list[Path]`,仅返回清单,不删文件
- [x] 4.2 `[impl]` 通过 FastAPI `lifespan` 起 `asyncio.create_task`,每 `LIFECYCLE_INTERVAL_S` 跑一次 scan,结果写 INFO 日志(用轻量 `asyncio.create_task` 方案,不引入 apscheduler;Open Question Q3 决议为此方案)
- [x] 4.3 `[impl]` `LIFECYCLE_DRY_RUN` 默认 true,`config.py` 注释里写明"C1 强制 true,真删随 C4 一起开放";lifespan 支持 `INFRA_DISABLE_LIFECYCLE=1` 测试环境跳过

## 5. 前端基础骨架

- [x] 5.1 `[impl]` `frontend/` 现状已经是 Vite + React 19 + TS 6 完整项目(遗留骨架),C1 只做增量补齐
- [x] 5.2 `[impl]` 配置 `vite.config.ts` dev server 端口 5173、代理 `/api` 与 `/demo` 到 `http://localhost:8000`;`/demo` 加 `bypass` 让 HTML 导航走前端路由、SSE (EventSource) 走后端代理
- [x] 5.3 `[impl]` `src/services/api.ts`:保留现状 `api.health()`(其他 projects/documents/analysis 属 C3/C4/C6 范围遗留代码,按 Option A 不动)
- [x] 5.4 `[impl]` `src/hooks/useSSE.ts`:基于 `EventSource` 的 hook,返回 status/latest/history
- [x] 5.5 `[impl]` 路由:`/`(HomePage 占位首页,展示 `/api/health` 结果)+ `/demo/sse`(SseDemoPage 订阅 `/demo/sse` 展示心跳)

## 6. 三层测试脚手架

- [x] 6.1 `[impl]` 后端 pytest:`backend/tests/unit/`、`backend/tests/e2e/`、`backend/tests/conftest.py`、`backend/tests/fixtures/__init__.py`
- [x] 6.2 `[impl]` LLM mock 统一入口:`backend/tests/fixtures/llm_mock.py`,`mock_llm_provider`/`mock_llm_provider_timeout`/`mock_llm_provider_rate_limit` fixtures + `MockLLMProvider` 类
- [x] 6.3 `[impl]` 前端 Vitest + RTL:装 `vitest`、`@testing-library/react`、`@testing-library/jest-dom`、`@testing-library/user-event`、`jsdom`,`vite.config.ts` 的 test 区块配置 + `src/test-setup.ts`(含 EventSource 占位以防 jsdom 缺失)
- [x] 6.4 `[impl]` `frontend/package.json` 加 `"test": "vitest run"` 与 `"test:watch": "vitest"` 脚本
- [x] 6.5 `[impl]` 项目根初始化 Playwright:根 `package.json` + `npm i -D @playwright/test tsx typescript @types/node`,`npx playwright install chromium --with-deps`
- [x] 6.6 `[impl]` 项目根 `e2e/` 目录:`e2e/fixtures/`、`e2e/seed.ts`(占位)、`playwright.config.ts`(baseURL `http://localhost:5173`,webServer 启 `npm --prefix frontend run dev`)
- [x] 6.7 `[impl]` 项目根 `package.json` 加 `"e2e"`、`"e2e:ui"`、`"e2e:install"`、`"seed"` 脚本 + `tsconfig.json`
- [x] 6.8 `[impl]` `.gitignore` 追加 `e2e/artifacts/`、`playwright-report/`、`test-results/`、项目根 `/node_modules/`

## 7. Docker compose

- [x] 7.1 `[impl]` `backend/Dockerfile` — 现状保留(遗留骨架,C1 不重写)
- [x] 7.2 `[impl]` `frontend/Dockerfile` — 现状保留(同上)
- [x] 7.3 `[impl]` `docker-compose.yml` 三服务:`postgres:16-alpine`(带 healthcheck)、`backend`(depends_on postgres healthy + healthcheck + LLM env 注入)、`frontend`
- [x] 7.4 `[impl]` `.env.example` 列出所有配置项,LLM provider 默认值敲定为 dashscope(Open Question Q1 决议)

## 8. L1 测试(单元+组件)

- [x] 8.1 `[L1]` 后端 `tests/unit/test_llm_mock_provider.py`:引用 `mock_llm_provider`,断言默认调用返回 `text="mocked"` 且 `error is None`
- [x] 8.2 `[L1]` 后端 `tests/unit/test_llm_timeout.py`:用 fixture `mock_llm_provider_timeout`/`mock_llm_provider_rate_limit`,断言返回结构化 error,不抛异常
- [x] 8.3 `[L1]` 后端 `tests/unit/test_lifecycle_dry_run.py`:临时目录放旧文件,调 `scan_expired`,断言清单包含该文件且文件仍在磁盘(2 cases:旧文件标记 + root 不存在返回空)
- [x] 8.4 `[L1]` 前端 `src/hooks/useSSE.test.tsx`:mock EventSource 驱动事件派发,断言 status 变 open + history 累积
- [x] 8.5 `[L1]` 前端 `src/services/api.test.ts`:mock `fetch`,断言 2xx 返回 JSON、非 2xx 抛错

**L1 运行结果**:后端 `pytest backend/tests/unit/` → 5 passed;前端 `npm test` → 3 passed(useSSE + api.test 2 cases)

## 9. L2 测试(API E2E)

- [x] 9.1 `[L2]` `tests/e2e/test_health.py`:httpx AsyncClient + ASGITransport 访问 `/api/health`,断言 200 + body.db=="ok"(真 postgres `localhost:5432/documentcheck`)
- [x] 9.2 `[L2]` `tests/e2e/test_sse_heartbeat.py`:用真实 uvicorn subprocess 启 app(避开 TestClient + StreamingResponse 在 Windows 下的 buffering 怪异),httpx stream 读前 8KB 断言含 `event: heartbeat`
- [x] 9.3 `[L2]` `tests/e2e/test_alembic_upgrade.py`:subprocess 跑 `python -m alembic upgrade head`(避免同 event loop 内 `asyncio.run` 冲突),再用 async engine 断言 `alembic_version` 表存在

**L2 运行结果**:`pytest backend/tests/e2e/` → 3 passed in 4.54s

## 10. L3 测试(UI E2E)

- [x] 10.1 `[L3]` `e2e/tests/smoke-home.spec.ts`:访问 `/`,断言 h1 含 "围标检测系统";同时通过 `page.request` 调用 `/api/health`(走前端代理)断言 200
- [x] 10.2 `[L3]` `e2e/tests/smoke-sse.spec.ts`:访问 `/demo/sse` 页(`waitUntil: "domcontentloaded"` 避开 SSE 长连接导致 load 永不触发),断言 `sse-count` testId 在 15s 内从 0 变非 0

**L3 运行结果**:`npm run e2e` → 3 passed in 3.6s(chromium,用 backend env `SSE_HEARTBEAT_INTERVAL_S=1` 加速)

## 11. 手工验证

- [x] 11.1 `[manual]` 原目标"`docker compose up` 一键启动全栈"因本机 Docker Desktop 存在 Windows kernel-lock 问题(`engine.sock` 无法释放)无法验证,**降级为本地三进程(PostgreSQL 16 服务 + uvicorn + vite)手工验证**。凭证文件:`e2e/artifacts/c1-manual-2026-04-14.md`。真实 `docker compose up` 验证作为 follow-up,待 Docker kernel-lock 问题解决后补齐(不阻塞 C1 归档)

## 12. 总汇

- [x] 12.1 跑 `[L1][L2][L3]` 全部测试,全绿
  - L1 后端:`pytest backend/tests/unit/` → **5 passed**
  - L1 前端:`cd frontend && npm test` → **3 passed**
  - L2:`pytest backend/tests/e2e/` → **3 passed**
  - L3:`npm run e2e` → **3 passed**
  - **合计 14 pass,0 fail**
