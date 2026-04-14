# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M1**(进行中,1/2 change 归档) |
| 当前 change | 待 C2 `auth` propose |
| 当前任务行 | N/A |
| 最新 commit | 待本次 archive commit(`归档 change: infra-base(M1)`) |
| 工作区 | 有大量未提交改动:backend 实现、frontend 实现、项目根 e2e + package.json、openspec 归档目录、docs 更新 |

---

## 2. 本次 session 关键决策(2026-04-14,C1 实施阶段)

### 设计层面
- **C1 范围收敛**:异步任务框架(asyncio + ProcessPoolExecutor)移至 C6(原 `propose` 阶段决议,execution-plan §3 C1 + §6 已记录)
- **遗留骨架策略 = 选项 A**:`backend/app/api/routes/{projects,documents,analysis}.py` 等超 C1 范围代码保留不动,C3/C4/C6 propose 时按"现状改造"处理
- **数据库路径 = `/api/health`**(与现有 `main.py` 一致,非 `/health`);spec 与 design 已对齐
- **Driver = asyncpg**(async,与现有 `db/session.py` 一致);design.md D1 已明确

### Open Question 决议(apply 阶段就地敲定)
- **Q1 LLM provider 默认 = dashscope**(国内可达性好;openai 也可通过配置切换)
- **Q2 Playwright 浏览器版本锁定 = 不单独锁**(随 `@playwright/test` 走,安装通过 `npx playwright install`)
- **Q3 生命周期调度 = 轻量 `asyncio.create_task`**(弃用 apscheduler,避免过度设计)

### 实施阶段硬阻塞与替代方案
- **Docker Desktop 无法启动**:遭遇 Windows kernel-lock bug(`C:\Users\7way\AppData\Local\docker-secrets-engine\engine.sock` 被系统持有,fsutil / del / ren 全失败,重启后依然复现)
- **方案切换**:本地装 PostgreSQL 16(winget)代替 Docker postgres;docker-compose.yml 保留不动,验收改用本地三进程
- **凭证**:`e2e/artifacts/c1-manual-2026-04-14.md` 记录降级方案 + 运行证据

### 实施阶段关键技术坑
- `alembic.ini` 中文注释 → Python cp936 解析报 UnicodeDecodeError;全改英文解决
- `asyncio.run()` 在 pytest-asyncio loop 里冲突;alembic test 改用 `subprocess.run(... alembic upgrade head)`
- pytest-asyncio function-scoped loop 与共享 async engine 冲突("Event loop is closed");改 pyproject 设 `asyncio_default_fixture_loop_scope = "session"` + `asyncio_default_test_loop_scope = "session"`
- ASGITransport + `request.is_disconnected()` 立即返 True → SSE generator 立即 break;改为仅靠 `CancelledError` 检测断开
- TestClient + StreamingResponse 在 Windows 下顽固 buffer;SSE 测试改为 subprocess 启真实 uvicorn + httpx stream
- vite proxy `/demo` 一刀切把浏览器导航也代理到后端 SSE(返 event-stream 给浏览器)→ 加 `bypass`:Accept text/html 走前端路由,其它(EventSource)才代理
- Playwright `page.goto("/demo/sse")` 默认 `waitUntil: "load"` 永不触发(SSE 长连接)→ 改用 `domcontentloaded`

---

## 3. 待确认 / 阻塞

- 无硬阻塞。
- **Follow-up(非 C1 归档阻塞)**:Docker Desktop kernel-lock 问题待解决;解决后回补 "docker compose up" 真实验证。

---

## 4. 下次开工建议

**一句话交接**:
> C1 `infra-base` 已归档(`openspec/changes/archive/2026-04-14-infra-base/`)。下一步 `/opsx:propose` 开 C2 `auth`(JWT + 失败计数 + 路由守卫 + 初始用户 seed + 改密)。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。C1 infra-base 已归档(openspec/specs/infra-base/spec.md
里有 10 个 requirement 作为地基)。
下一步开 C2 auth:JWT 登录 + 失败计数 + 账户锁定 + 路由守卫 + 初始用户 seed + 改密。
参考 docs/execution-plan.md §3 C2 小节的核心能力与验证场景。
请先读 docs/handoff.md 确认现状,然后 openspec-propose 为 C2 生成 artifacts。
tasks.md 按 CLAUDE.md OpenSpec 集成约定打 [impl]/[L1]/[L2]/[L3]/[manual] 标签。
```

**C2 前的预备条件(已就绪)**:
- PostgreSQL 16 本地服务已跑(`postgresql-x64-16` 服务,5432 端口),`documentcheck` 数据库已建
- `alembic upgrade head` 走通,后续 change 可直接写业务迁移
- 三层测试脚手架就位,C2 只需补 C2 scope 的 L1/L2/L3 用例

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-14 | **C1 `infra-base` 归档**:14 pass 0 fail(L1 8 + L2 3 + L3 3);本地 PostgreSQL 替 Docker;LLM 适配层(dashscope+openai)/SSE/DB pool_pre_ping/生命周期 dry-run/三层测试脚手架 全部落地 |
| 2026-04-14 | C1 `infra-base` propose 完成(4 个 artifact);C1 范围收敛,异步任务框架移至 C6 |
| 2026-04-14 | 首版 Handoff 落地,配合 execution-plan.md + CLAUDE.md 测试标准一起上线 |
