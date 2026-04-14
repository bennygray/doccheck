## Context

DocumentCheck 第一期严格按 17 个 capability 级 change 串行推进(详见 `docs/execution-plan.md`)。C1 `infra-base` 是首个 change,目的是把后续 16 个 change 都依赖的"地基"先打稳:数据库连接与迁移、健康检查、SSE 推送通道、LLM 适配层、生命周期管理、前端骨架,以及 CLAUDE.md 里规定的三层分层测试脚手架(L1/L2/L3)。

**约束**:
- 技术栈已锁定(`CLAUDE.md`):后端 Python 3.12+ / FastAPI / SQLAlchemy 2.x / Alembic,前端 React + TS / Vite,数据库 PostgreSQL,后端依赖管理 uv
- 测试标准已锁定(`CLAUDE.md` 测试标准):L1=Vitest+RTL/pytest,L2=pytest+TestClient,L3=项目根 `e2e/` 下的 Playwright,baseURL 默认 `http://localhost:5173`
- LLM 在测试里默认 mock,统一入口 `backend/tests/fixtures/llm_mock.py`
- 异步任务框架已迁出本 change(到 C6)

**当前状态(apply 阶段审计更新,2026-04-14)**:仓库里 `backend/` 与 `frontend/` 已有**预置骨架**,不是 greenfield。具体:
- `backend/app/` 已有 `main.py`(挂载 `/api/health` + CORS + `projects/documents/analysis` 三个占位路由)、`core/config.py`、`db/session.py`(async engine + asyncpg)、`db/base.py`(DeclarativeBase)
- `backend/alembic/` 目录存在但 **未真正初始化**(无 `alembic.ini`、无 `env.py`),versions 目录为空
- `frontend/` 已是 Vite + React 19 + TS 6 完整项目,有 `src/App.tsx` / `main.tsx` / `services/api.ts`,已装 `node_modules`
- `docker-compose.yml` 已存在(postgres + backend + frontend 三服务,backend 用 asyncpg URL)
- `backend/Dockerfile`、`frontend/Dockerfile` 已存在

**超 C1 范围的遗留代码处理策略(选项 A,2026-04-14 敲定)**:
- `api/routes/projects.py`、`documents.py`、`analysis.py` 为 C3/C4/C6 范围,C1 不纳入验收,保留现状
- C1 apply **不修改**这三个路由文件,也不删除
- C3 / C4 / C6 各自 propose 时按"现状改造"而非"从零落地"处理,届时若需重写再重写
- `services/parser/analyzer/detector/` 三个空目录同理

本 change 采取"**缺什么补什么**"的增量策略,避免重写已有骨架。

## Goals / Non-Goals

**Goals**:
- 后端可以 `uvicorn app.main:app --reload` 启动并 `GET /health` 通
- `alembic upgrade head` 成功(即使本 change 不引入业务表,迁移框架本身要可用)
- `GET /demo/sse` 能持续推送心跳事件,客户端断开后服务端不报错
- LLM 适配层提供单一接口,可在不改业务代码的前提下切换 provider,异常时返回结构化 error(由上层决定降级)
- 生命周期 dry-run 任务能跑、能列出"理论上要清理的文件",但不真删
- 前端 `npm run dev` 可启动,空壳页面可访问
- 三层测试都有"hello-world 级"用例并全绿(为后续 change 提供可复制的样板)
- `docker compose up` 后,前后端 + DB 全部就绪

**Non-Goals**:
- 不实现任何业务能力(无登录、无项目管理、无文件上传、无检测)
- 不实现异步任务框架(已迁出至 C6)
- 不引入业务表(只验证迁移框架本身可用)
- 不实现真实的文件清理(只 dry-run)
- 不做生产级 LLM provider 选型评估(本 change 只搭壳;dashscope/openai 二选一即可启动)

## Decisions

### D1. 数据库迁移框架:Alembic + async(直接用,不二次封装)
- **选择**:用 Alembic 官方 CLI,`alembic init` 生成的标准布局放在 `backend/alembic/`
- **Driver**:**asyncpg**(与现有 `db/session.py` 一致),`env.py` 使用 `async_engine_from_config` + `run_sync` 模式
- **Health 路径**:`/api/health`(与现有 `main.py` 一致,前端通过 `/api` 代理访问)
- **替代方案**:自研轻量迁移、或用 SQLModel 自带迁移、或切回同步 psycopg
- **理由**:Alembic 是 SQLAlchemy 官方推荐方案;asyncpg 与 FastAPI 异步栈匹配,无需引入额外同步 driver
- **现在不做**:不做迁移自动生成的 CI 检查(留到 C2 第一个真实业务表落地时再补)

### D2. SSE 实现:`StreamingResponse` + 异步生成器(不引第三方 SSE 库)
- **选择**:FastAPI 原生 `StreamingResponse`,`Content-Type: text/event-stream`,`/demo/sse` 用 `asyncio.sleep(15)` 推心跳
- **替代方案**:`sse-starlette`、或基于 WebSocket
- **理由**:原生方案足够,少一层依赖;真正复杂的 SSE(C6 检测进度推送)再评估是否升级
- **客户端断开**:`StreamingResponse` 内捕获 `asyncio.CancelledError`,记录日志后正常返回(服务端幂等)

### D3. LLM 适配层:Protocol + Adapter,降级由上层决定
- **接口**:定义 `LLMProvider` Protocol(`async def complete(prompt, **opts) -> LLMResult`),实现 `DashScopeProvider` 与 `OpenAIProvider`,通过 `LLM_PROVIDER` 环境变量选择
- **降级策略**:**适配层只负责返回结构化 error(`LLMResult.error` 字段)**,不在适配层内做兜底重试或 fallback。降级策略由调用方(如 C5 Parser、C7~C14 Detection Agents)决定 —— 每个 Agent 的兜底是不同的(规则兜底、本地向量、跳过等)
- **替代方案**:在适配层做统一重试与兜底
- **理由**:不同消费者需要不同的降级行为(Parser 要走规则兜底,某些 Agent 要切本地算法,有的直接跳过),硬塞到适配层会过度设计
- **超时/限流**:统一在适配层做,超时→`LLMResult.error.kind = "timeout"`;限流→`LLMResult.error.kind = "rate_limit"`

### D4. 生命周期清理:dry-run 默认开启,真删延后
- **选择**:用 `apscheduler` 起一个后台定时任务,扫描"过期"文件(规则:占位逻辑 — 修改时间超过 N 天),输出清单到日志,不调 `os.remove`
- **替代方案**:Celery、自研
- **理由**:`apscheduler` 进程内即可,无需额外 broker;C1 阶段 dry-run 足够,真删要等 C4 file-upload 落地后才有真实文件
- **配置**:`LIFECYCLE_DRY_RUN=true`(默认,本 change 不允许 false)、`LIFECYCLE_INTERVAL_S=3600`、`LIFECYCLE_AGE_DAYS=30`

### D5. 测试三层目录与命令
| 层 | 工具 | 位置 | 命令 |
|---|---|---|---|
| L1 后端 | pytest | `backend/tests/unit/` | `pytest backend/tests/unit/` |
| L1 前端 | Vitest + RTL | `frontend/src/**/*.test.tsx` | `npm test`(在 `frontend/` 内) |
| L2 | pytest + TestClient + httpx | `backend/tests/e2e/` | `pytest backend/tests/e2e/` |
| L3 | Playwright + TS | 项目根 `e2e/` | `npm run e2e`(在项目根) |

- **项目根 `package.json`**:仅承载 Playwright 与 `seed.ts` 所需依赖,`scripts.e2e` = `playwright test`,`scripts.seed` = `tsx e2e/seed.ts`
- **替代方案**:把 Playwright 放进 `frontend/`
- **理由**:CLAUDE.md 已明确要求 `e2e/` 独立于 `frontend/`(便于后续 docker compose 产物联调,也避免前端构建变慢)

### D6. LLM mock:单一 fixture 文件,所有测试共享
- `backend/tests/fixtures/llm_mock.py` 提供 `mock_llm_provider`(pytest fixture)和 `MockLLMProvider`(类,可被 monkeypatch 替换 DI 容器里的 provider)
- 默认行为:返回固定 `LLMResult(text="mocked", error=None)`;支持构造异常分支(超时、限流)
- **替代方案**:每个测试自己 mock
- **理由**:8 个 LLM 调用点(L-1/L-2 + 7 个文本相似类 Agent)将共用,统一入口避免 mock 行为漂移

### D7. 前端骨架最小化
- 路由仅一个 `/` 占位页 + 一个 `/demo/sse` 演示页
- API client 用 `fetch` 简单封装(`apiGet/apiPost`),不引 `axios`(过度设计)
- SSE 客户端:`useSSE(url)` hook,基于浏览器原生 `EventSource`,内置自动重连(浏览器原生支持)
- **替代方案**:引入完整状态管理(zustand/redux)、数据请求库(react-query)
- **理由**:这些都是 C2/C3 才需要的;现在引入是过度设计

### D8. Docker compose
- 三服务:`postgres:16-alpine`、`backend`(Dockerfile multi-stage)、`frontend`(Vite dev server)
- 不引入 nginx/反向代理(开发环境直接访问 5173 / 8000)
- **替代方案**:加 nginx
- **理由**:开发场景不需要;生产部署是后续考虑

## Risks / Trade-offs

- **[Risk] Windows 与 Docker 路径差异** → 所有路径用 POSIX 风格;`docker-compose.yml` volumes 使用相对路径
- **[Risk] uv 在 CI/Docker 内的可用性** → Dockerfile 显式安装 uv;本地开发 README 写明必装 uv
- **[Risk] Playwright 浏览器二进制体积大,首次安装慢** → README 说明 + `npx playwright install --with-deps` 一次性安装;CI 缓存策略留到后续 change 再优化
- **[Risk] LLM 适配层"上层决定降级"会让上层重复实现 try/except** → 提供 `with_fallback(primary_call, fallback_fn)` 工具函数(放在 `app/services/llm/`),消费者按需用;不强制
- **[Risk] dry-run 永远没真删,会被遗忘** → 在 `LIFECYCLE_DRY_RUN` 配置项注释里写明 "C1 强制 true,真删随 C4 一起开放";`docs/execution-plan.md` 也已记录
- **[Trade-off] 不做异步任务框架,意味着 C1 没办法演示 "提交任务→后台跑→SSE 推进度" 的完整闭环** → 接受;C1 只演示 SSE 心跳即可,完整闭环留 C6
- **[Trade-off] LLM 适配层不内置 fallback,初期消费者会觉得"麻烦"** → 接受;不同 Agent 兜底差异很大,统一兜底是过度设计

## Migration Plan

本 change 是 greenfield 落地,无需迁移。

**部署步骤**(给 apply 阶段参考):
1. 后端:`cd backend && uv sync && alembic upgrade head && uvicorn app.main:app --reload`
2. 前端:`cd frontend && npm install && npm run dev`
3. 一键:`docker compose up`
4. 三层测试:`pytest backend/tests/unit/` + `cd frontend && npm test` + `pytest backend/tests/e2e/` + `npm run e2e`(项目根)

**回滚**:本 change 仅新增文件,无破坏性变更。若失败,直接 `git revert` 即可,无 DB 数据残留(因为没有业务表)。

## Open Questions

- **Q1**:LLM provider 默认值选 dashscope 还是 openai?
  - 建议:默认 dashscope(国内可达性更好),`.env.example` 写明两个 key 都可填
  - **决议时机**:apply 阶段,写 `.env.example` 时一句话敲定
- **Q2**:Playwright 浏览器是否一并锁版本到 lock 文件?
  - 建议:用 `@playwright/test` 自带的浏览器版本管理,不额外锁;由 `npx playwright install` 控制
  - **决议时机**:apply 阶段第 11 节 L3 测试落地时
- **Q3**:`apscheduler` 还是 FastAPI `lifespan` + `asyncio.create_task`?
  - 建议:用后者(更轻),`apscheduler` 是过度设计 —— 修订决策 D4
  - **决议时机**:apply 阶段第 6 节生命周期任务落地时,如确认不需要复杂调度,直接 `asyncio.create_task` + `while True: await sleep + run`
