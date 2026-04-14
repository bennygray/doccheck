## Why

C5 完成后,"上传压缩包 → 自动解析 → 看到投标人 + 文件角色 + 报价" 端到端打通,M2 进度 3/3。项目状态推进到 `ready`,但"启动检测 → 10 Agent 并行 → SSE 进度 → 综合研判 → 看报告"这条 M3 主链路仍为空壳:后端 `POST /api/projects/{pid}/analysis/start` 未实现、无 AgentTask / PairComparison / OverallAnalysis / AnalysisReport 表、无异步检测调度、无 Agent 注册表、前端无报告页。

C6 把**异步任务框架 + 10 Agent 骨架(自检/skipped 全落地,dummy run)+ Agent 并行调度 + SSE 进度推送 + 综合研判占位 + 通用任务表(消化 C4/C5 遗留 event loop 重启丢任务)**一次打通,作为 M3 首个 change。后续 C7~C13 只需填各 Agent 的 `run()` 实现,框架不再改。

本次 propose 已与用户敲定 4 项关键边界(详见 design.md):

- **A1 整体做**:US-5.1~5.4 全做,接受 ~13 Requirement / ~45-50 Scenario(与 C5 同量级)
- **B1 409 拒绝**:项目 `analyzing` 态再次启动检测 → 409 `{current_version, started_at}`,不做 resume/覆盖语义
- **C2 10 Agent 注册表 + dummy run**:10 Agent 的 name / agent_type(pair/global)/ preflight(前置条件自检)在 C6 落地为稳定 contract,`run()` 全部走 dummy(sleep + 随机分);真实 run 留 C7~C13
- **D3 通用 `async_tasks` 表 + 只扫不自动恢复**:4 subtype(extract / content_parse / llm_classify / agent_run)通用任务表,启动时扫 stuck 任务 → 标 timeout + 实体状态回滚,不做自动重调,由用户手动重试(已有端点复用);完整吃掉 C4/C5 遗留

## What Changes

### 数据模型(5 张新表 + alembic 0005)

- **`agent_tasks`**:`id / project_id FK / version / agent_name / agent_type(pair|global) / pair_bidder_a_id / pair_bidder_b_id / status(6态:pending/running/succeeded/failed/timeout/skipped)/ started_at / finished_at / elapsed_ms / score / summary / error / created_at`;索引 `(project_id, version)` + `(status, started_at)`
- **`pair_comparisons`**:`id / project_id / version / bidder_a_id / bidder_b_id / dimension / score / evidence_json(JSONB)/ is_ironclad / created_at`;US-5.2 AC-6 分类存储
- **`overall_analyses`**:`id / project_id / version / dimension / score / evidence_json / created_at`
- **`analysis_reports`**:`id / project_id / version / total_score / risk_level(high|medium|low)/ llm_conclusion(C6 留空,C14 填)/ created_at`;UNIQUE(project_id, version);**行存在 = 检测完成**的状态信号
- **`async_tasks`**(D3):`id / subtype(extract|content_parse|llm_classify|agent_run)/ entity_type / entity_id / status(running|done|timeout|failed)/ heartbeat_at / started_at / finished_at / error / created_at`;索引 `(status, heartbeat_at)` 支撑 scanner 扫描

### 后端端点(4 个新)

- `POST /api/projects/{pid}/analysis/start` — 前置校验(≥2 bidder、所有 bidder 进终态、无 `identifying/pricing` 进行中);创建 AgentTask × N + 触发异步调度;**analyzing 态 → 409** `{current_version, started_at}`;201 返 `{version, agent_task_count}`
- `GET /api/projects/{pid}/analysis/status` — 当前 version 所有 Agent 快照(SSE 重连恢复用);返 `{version, project_status, agent_tasks: [...]}`
- `GET /api/projects/{pid}/analysis/events`(SSE 长连接)— 复用 `progress_broker`,事件类型 `agent_status / report_ready / heartbeat`;payload schema 见 requirements §4.4.1
- `GET /api/projects/{pid}/reports/{version}` — 报告骨架,返 `{version, total_score, risk_level, dimensions: [10 个维度得分 + summary]}`;详细 4 Tab(概要/对比/维度分析/检测日志)留 **C14**

### 后端服务(3 个新子模块)

- **`app/services/detect/`**:
  - `registry.py`:`@register_agent(name, agent_type, preflight)` 装饰器 + `AGENT_REGISTRY` 模块级 dict + `get_all_agents() / get_agent(name)`;10 Agent 注册表
  - `preflight.py`:11 行前置条件自检规则(对应 US-5.2 表格),含"错误一致性降级运行"特殊语义(identity_info 为空 → 降级而非 skipped)
  - `engine.py`:orchestrator(建 AgentTask 行 → asyncio.gather(return_exceptions=True)→ 单 Agent 超时 5min + 全局 30min + Agent 级 run_in_executor hook);异常/超时隔离不影响其他
  - `judge.py`:综合研判占位 — 按 requirements §F-RP-01 10 维度加权求和 → total_score + risk_level;LLM 结论字段留空,标 "AI 研判暂不可用"(C6 不调 LLM)
  - `agents/{text_sim,section_sim,structure_sim,metadata_author,metadata_time,metadata_machine,price_consistency,error_consistency,style,image_reuse}.py`:10 个骨架文件,各含 `@register_agent` 声明 + dummy `run(ctx)`(sleep 0.2~1.0s + 随机 0~100 分)
- **`app/services/async_tasks/`**:
  - `tracker.py`:上下文管理器 `async with track(subtype, entity_type, entity_id):`,内部 INSERT async_tasks 行 + 启后台心跳协程(每 30s UPDATE heartbeat_at)+ finally DELETE 行
  - `scanner.py`:启动时 `scan_and_recover()`:扫 `status='running' AND heartbeat_at < now()-60s` → 按 subtype 分派回滚 handler(bidder 回 `*_failed`,agent_task 回 `timeout`,project `analyzing` 回 `ready`);每个 handler 独立,失败不互相影响
  - 复用 C5 `progress_broker`:C6 只扩展事件 schema,新增 `agent_status / report_ready` 两个 event type

### 前端(4 新 + 2 改)

- `hooks/useDetectProgress.ts`:EventSource + onerror 降级 3s 轮询 `/analysis/status`(C5 模式复用)
- `components/detect/StartDetectButton.tsx`:前置条件 hover 提示(<2 bidder / 解析未完成 / 正在检测中)+ loading + 409 处理(跳转进度面板)
- `components/detect/DetectProgressIndicator.tsx`:进度条 `N/10 维度完成` + 一行最新摘要(US-5.3 轻量版,非重型面板)
- `pages/reports/ReportPage.tsx`:骨架,仅 **Tab1 总览**(风险等级徽章 + 总分 + 10 维度得分列表占位);Tab2-4 留 C14
- 改 `pages/projects/ProjectDetailPage.tsx`:集成 StartDetectButton + DetectProgressIndicator;检测完成跳转 `/reports/:pid/:version`
- 改 `services/api.ts`:新增 4 方法(startAnalysis / getAnalysisStatus / subscribeDetectEvents / getReport)
- 改 `types/index.ts`:`AgentTask / AgentTaskStatus(6态)/ PairComparison / OverallAnalysis / AnalysisReport / DetectEvent / RiskLevel` 类型

### 测试 + 基础设施

- **L1**:Agent 注册表 / preflight / engine 超时异常隔离 / judge 占位公式 / tracker 上下文管理器 / scanner 恢复逻辑 / 4 前端组件 / useDetectProgress hook
- **L2**:启动检测 API(含 409 + 前置校验)/ status / SSE 事件流 / reports 骨架 / async_tasks scanner(模拟 stuck → 启 scanner → 验回滚)
- **L3**:启动检测 → SSE 进度 → 查看报告骨架(延续 C5 precedent,若 Docker Desktop kernel-lock 未解除则降级手工凭证)
- `INFRA_DISABLE_DETECT=1` 测试开关(与 PIPELINE/EXTRACT/LIFECYCLE 一致模式)
- `clean_users` fixture 扩 5 表(`async_tasks → analysis_reports → overall_analyses → pair_comparisons → agent_tasks` 按 FK 顺序在 projects 前)

## Capabilities

### New Capabilities

- `detect-framework`: 异步检测框架(启动 API + 10 Agent 注册表 + Agent 并行调度 + SSE 进度推送 + 综合研判骨架 + 通用任务表重启恢复);覆盖 US-5.1 ~ US-5.4 全部 AC

### Modified Capabilities

- `project-mgmt`: `GET /api/projects/{id}` 详情响应新增 `analysis` 字段 `{current_version, status, agent_task_count, ...}`(C3 阶段 NULL → C6 非 NULL);`projects.status` 枚举 `analyzing` 态由本次 change 首次写入(C3 已预留字符串值但无业务逻辑触发)
- `parser-pipeline`: 无 spec 修改;仅 `async_tasks.subtype` 覆盖 C5 的 content_parse / llm_classify(运行时兼容,不改 C5 spec 行为)

## Impact

### 受影响代码

- **新增后端**(~40-50 文件):
  - `app/models/{agent_task, pair_comparison, overall_analysis, analysis_report, async_task}.py` 5 模型
  - `alembic/versions/0005_detect_framework.py`
  - `app/services/detect/{registry, preflight, engine, judge}.py` + `app/services/detect/agents/*.py` 10 Agent 骨架
  - `app/services/async_tasks/{tracker, scanner}.py`
  - `app/api/routes/{analysis, reports}.py`
  - `app/schemas/{agent_task, analysis, report, detect_event}.py`
  - `tests/unit/` + `tests/e2e/` 对应测试文件 ~20 个
- **新增前端**(~8-10 文件):
  - `hooks/useDetectProgress.ts`
  - `components/detect/{StartDetectButton, DetectProgressIndicator}.tsx`
  - `pages/reports/ReportPage.tsx`
  - 对应 `__tests__/` 测试 4 个
- **修改后端**(~8 文件):
  - `models/__init__.py`(注册 5 模型)
  - `api/routes/projects.py`(详情响应加 `analysis` 字段)
  - `api/routes/__init__.py` 或 `main.py`(注册 analysis / reports router + 启动时调 `scanner.scan_and_recover()`)
  - `services/extract/engine.py` + `services/parser/content/__init__.py` + `services/parser/llm/role_classifier.py`(用 `async with track()` 包裹已有异步任务,吃掉 C4/C5 遗留)
  - `tests/fixtures/auth_fixtures.py`(clean_users 扩 5 表)
  - `tests/fixtures/llm_mock.py`(新增 `mock_llm_judge_*` fixture,C6 不调但 C14 需要)
- **修改前端**(~5 文件):`pages/projects/ProjectDetailPage.tsx` / `services/api.ts` / `types/index.ts` / `pages/ReportPage` 路由注册 / `components/projects/FileTree.tsx`(无改动,仅兼容)

### 依赖

- 无新系统/Python/npm 依赖(全部走 asyncio + SQLAlchemy + 复用 C5 broker)
- 环境变量:无新增(LLM 变量 C5 已配,C6 暂不调 LLM)

### API 变更

- 新增 4 端点(见上)
- `GET /api/projects/{id}` 响应新增 `analysis: {current_version, status, agent_task_count} | null`

### 运行时变更

- 后端启动 hook 新增 `scanner.scan_and_recover()` 一次性扫描(同步阻塞直至完成,避免启动后有窗口期让用户误以为任务在跑但其实已 stuck)
