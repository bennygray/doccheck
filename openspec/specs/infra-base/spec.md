# infra-base Specification

## Purpose
TBD - created by archiving change infra-base. Update Purpose after archive.
## Requirements
### Requirement: 数据库连接与迁移框架
系统 SHALL 提供基于 SQLAlchemy 2.x 的 PostgreSQL 数据库连接,并通过 Alembic 管理 schema 迁移。

#### Scenario: 执行 alembic upgrade head
- **WHEN** 在 `backend/` 目录下执行 `alembic upgrade head`
- **THEN** 命令成功退出(exit code 0),且数据库中存在 `alembic_version` 表

#### Scenario: 数据库连接断开后自动重连
- **WHEN** PostgreSQL 短暂不可用后恢复
- **THEN** 应用 SHALL 在下一次请求时成功重新建立连接,无需重启服务

---

### Requirement: 健康检查端点
系统 SHALL 暴露 `GET /api/health` 端点用于服务存活与依赖连通性检查。

#### Scenario: 服务正常时返回 200
- **WHEN** 客户端访问 `GET /api/health`,且 PostgreSQL 可达
- **THEN** 响应 SHALL 返回 HTTP 200,且 body 至少包含 `{"status": "ok", "db": "ok"}`

#### Scenario: 数据库不可达时返回 503
- **WHEN** 客户端访问 `GET /api/health`,但 PostgreSQL 不可达
- **THEN** 响应 SHALL 返回 HTTP 503,且 body 包含 `{"status": "degraded", "db": "unreachable"}`

---

### Requirement: SSE 推送基础
系统 SHALL 提供基于 Server-Sent Events 的推送基础设施,并通过 `GET /demo/sse` 端点演示心跳能力。

#### Scenario: 客户端连接后持续收到心跳
- **WHEN** 客户端建立到 `GET /demo/sse` 的持久连接
- **THEN** 服务端 SHALL 在 30 秒内至少推送 1 条心跳事件(`event: heartbeat`)

#### Scenario: 客户端断开后服务端幂等处理
- **WHEN** 客户端在接收过程中断开连接
- **THEN** 服务端 SHALL 不抛出未处理异常,不影响其他正在进行的 SSE 连接

#### Scenario: 前端 SSE 客户端自动重连
- **WHEN** 前端通过 `useSSE` hook 订阅 `/demo/sse`,网络中断后恢复
- **THEN** 客户端 SHALL 自动重新建立连接并继续接收事件

---

### Requirement: LLM 适配层
系统 SHALL 提供统一的 LLM Provider 接口,支持多 provider 配置切换,并对超时与限流返回结构化 error。

#### Scenario: 通过统一接口调用 mock provider
- **WHEN** 单元测试通过 `LLMProvider.complete(prompt)` 调用注入的 mock provider
- **THEN** 调用 SHALL 成功返回 `LLMResult`,且 `text` 字段非空、`error` 字段为 `None`

#### Scenario: 超时返回结构化 error,不抛异常
- **WHEN** LLM 调用超过配置的 `LLM_TIMEOUT_S` 阈值
- **THEN** `complete()` SHALL 返回 `LLMResult(text="", error=Error(kind="timeout", ...))`,**不**向调用方抛出异常

#### Scenario: 限流返回结构化 error
- **WHEN** LLM provider 返回 429 / rate-limit 错误
- **THEN** `complete()` SHALL 返回 `LLMResult(text="", error=Error(kind="rate_limit", ...))`

#### Scenario: 降级策略由调用方决定
- **WHEN** 调用方收到 `LLMResult.error != None`
- **THEN** 调用方 SHALL 自行决定降级行为(规则兜底/本地算法/跳过),适配层 SHALL NOT 内置自动 fallback

---

### Requirement: 数据生命周期 dry-run 任务
系统 SHALL 提供后台定时任务,周期性扫描过期文件并输出"待清理"清单,但 SHALL NOT 在 C1 阶段执行真实删除。

#### Scenario: dry-run 默认开启
- **WHEN** 应用启动且未显式覆盖 `LIFECYCLE_DRY_RUN`
- **THEN** 配置项 SHALL 默认为 `true`,清理任务 SHALL 仅记录"待删清单"到日志,不调用任何文件删除 API

#### Scenario: 标记过期文件不删除
- **WHEN** dry-run 任务扫描到修改时间超过 `LIFECYCLE_AGE_DAYS` 的文件
- **THEN** 任务 SHALL 输出该文件路径与最后修改时间到日志,且文件 SHALL 在磁盘上保留

---

### Requirement: 前端基础骨架
系统 SHALL 提供基于 Vite + React + TypeScript 的前端骨架,包含路由、API client、SSE 客户端封装。

#### Scenario: 开发服务器可启动
- **WHEN** 在 `frontend/` 目录下执行 `npm install && npm run dev`
- **THEN** Vite SHALL 在 `http://localhost:5173` 启动,首页 SHALL 可访问且无控制台错误

#### Scenario: SSE demo 页接收心跳
- **WHEN** 用户访问前端 `/demo/sse` 页面
- **THEN** 页面 SHALL 在 30 秒内显示至少一条心跳事件

---

### Requirement: 三层测试脚手架
系统 SHALL 提供三层分层测试脚手架(L1 单元/组件、L2 API E2E、L3 UI E2E),每层 SHALL 至少包含一条样板用例。

#### Scenario: L1 后端 pytest 可运行
- **WHEN** 执行 `pytest backend/tests/unit/`
- **THEN** 命令 SHALL 退出码为 0,至少 1 个用例通过

#### Scenario: L1 前端 Vitest 可运行
- **WHEN** 在 `frontend/` 目录执行 `npm test`
- **THEN** 命令 SHALL 退出码为 0,至少 1 个用例通过

#### Scenario: L2 API E2E 可运行
- **WHEN** 执行 `pytest backend/tests/e2e/`
- **THEN** 命令 SHALL 退出码为 0,至少 1 个用例通过(覆盖 `/api/health`)

#### Scenario: L3 Playwright 可运行
- **WHEN** 在项目根执行 `npm run e2e`
- **THEN** 命令 SHALL 退出码为 0,至少 1 个冒烟用例通过

---

### Requirement: LLM mock 统一入口
系统 SHALL 提供唯一的 LLM mock fixture 文件 `backend/tests/fixtures/llm_mock.py`,所有需要 mock LLM 的测试 SHALL 通过此入口共享。

#### Scenario: 默认 mock 返回固定结果
- **WHEN** 单元测试引用 `mock_llm_provider` fixture 不做额外配置
- **THEN** mock provider 的 `complete()` SHALL 返回 `LLMResult(text="mocked", error=None)`

#### Scenario: mock 可构造异常分支
- **WHEN** 单元测试通过 fixture 参数指定 `error_kind="timeout"`
- **THEN** mock provider 的 `complete()` SHALL 返回 `LLMResult(text="", error=Error(kind="timeout", ...))`

---

### Requirement: 一键启动编排
系统 SHALL 提供 `docker-compose.yml` 一键启动 backend、frontend、postgres 三个服务。

#### Scenario: docker compose up 全栈就绪
- **WHEN** 在项目根执行 `docker compose up`
- **THEN** 三个服务 SHALL 全部进入 healthy 状态,backend `/api/health` 在容器网络内可访问且返回 200

---

### Requirement: 测试产物隔离
系统 SHALL 将 L3 测试产物目录加入版本控制忽略,避免截图/录屏污染 git 历史。

#### Scenario: e2e/artifacts/ 不入 git
- **WHEN** Playwright 运行后在 `e2e/artifacts/` 写入截图或 trace 文件
- **THEN** `.gitignore` SHALL 包含 `e2e/artifacts/`,`git status` SHALL NOT 显示这些文件

