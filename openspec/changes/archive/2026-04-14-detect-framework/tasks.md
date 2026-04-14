## 1. 后端数据层(5 张新表 + alembic 0005)

- [x] 1.1 [impl] 新增 `backend/app/models/agent_task.py`:`AgentTask` 模型(字段按 spec);索引 `(project_id, version)` + `(status, started_at)`;PostgreSQL CHECK 约束(pair/global 对应 pair_bidder 字段的非空组合);SQLite 退化应用层保证
- [x] 1.2 [impl] 新增 `backend/app/models/pair_comparison.py`:`PairComparison` 模型;evidence_json JSONB(SQLite JSON);索引 `(project_id, version, dimension)`
- [x] 1.3 [impl] 新增 `backend/app/models/overall_analysis.py`:`OverallAnalysis` 模型;同上
- [x] 1.4 [impl] 新增 `backend/app/models/analysis_report.py`:`AnalysisReport` 模型;UNIQUE `(project_id, version)`;llm_conclusion TEXT NOT NULL DEFAULT ''
- [x] 1.5 [impl] 新增 `backend/app/models/async_task.py`:`AsyncTask` 模型;索引 `(status, heartbeat_at)` 支撑 scanner
- [x] 1.6 [impl] 更新 `backend/app/models/__init__.py`:注册 5 个新模型
- [x] 1.7 [impl] 新增 `backend/alembic/versions/0005_detect_framework.py`:CREATE 5 张表 + 索引 + CHECK(PostgreSQL)+ UNIQUE;含 downgrade 按 FK 反序 DROP
- [x] 1.8 [impl] 双向迁移验证:`alembic upgrade head` / `alembic downgrade 0004_parser_pipeline` / `alembic upgrade head`

## 2. 后端服务层 — detect/registry + preflight + agents 骨架

- [x] 2.1 [impl] 新增 `backend/app/services/detect/__init__.py`:空 __init__
- [x] 2.2 [impl] 新增 `backend/app/services/detect/registry.py`:`AgentSpec` namedtuple + `AGENT_REGISTRY: dict[str, AgentSpec]` + `@register_agent(name, agent_type, preflight)` 装饰器;重复注册抛 `ValueError`
- [x] 2.3 [impl] 新增 `backend/app/services/detect/context.py`:`AgentContext dataclass`(project_id / version / agent_task / bidder_a / bidder_b / all_bidders / llm_provider / session / downgrade);`PreflightResult`、`AgentRunResult` namedtuple
- [x] 2.4 [impl] 新增 `backend/app/services/detect/agents/__init__.py`:从下列 10 个模块 import * 触发注册
- [x] 2.5 [impl] 新增 `backend/app/services/detect/agents/text_similarity.py`:preflight(同角色文档)+ dummy run(写 PairComparison)
- [x] 2.6 [impl] 新增 `backend/app/services/detect/agents/section_similarity.py`:同上
- [x] 2.7 [impl] 新增 `backend/app/services/detect/agents/structure_similarity.py`:同上
- [x] 2.8 [impl] 新增 `backend/app/services/detect/agents/metadata_author.py`:preflight(双方 metadata.author 非空)+ dummy run
- [x] 2.9 [impl] 新增 `backend/app/services/detect/agents/metadata_time.py`:preflight(双方 modified_at 非空)+ dummy run
- [x] 2.10 [impl] 新增 `backend/app/services/detect/agents/metadata_machine.py`:preflight(双方 app_version/template 非空)+ dummy run
- [x] 2.11 [impl] 新增 `backend/app/services/detect/agents/price_consistency.py`:preflight(双方 priced 且 price_items 非空)+ dummy run
- [x] 2.12 [impl] 新增 `backend/app/services/detect/agents/error_consistency.py`(global):preflight 支持 downgrade 状态(identity_info 空 → downgrade)+ dummy run 写 OverallAnalysis
- [x] 2.13 [impl] 新增 `backend/app/services/detect/agents/style.py`(global):preflight(≥2 bidder 同角色)+ dummy run 写 OverallAnalysis
- [x] 2.14 [impl] 新增 `backend/app/services/detect/agents/image_reuse.py`(global):preflight(≥2 bidder 有 document_images)+ dummy run

## 3. 后端服务层 — detect/engine + judge

- [x] 3.1 [impl] 新增 `backend/app/services/detect/engine.py`:
  - 模块级 `_CPU_EXECUTOR: ProcessPoolExecutor | None = None` + `get_cpu_executor()` lazy init + `shutdown_cpu_executor()` 释放
  - `async def run_detection(project_id, version)`:顶层 orchestrator
  - `async def _run_single_agent_task(agent_task_id)`:单 Agent 执行(preflight → wait_for run)+ 心跳 tracker 外包裹 + broker publish
  - 超时常量 `AGENT_TIMEOUT_S=300` / `GLOBAL_TIMEOUT_S=1800`(环境变量可覆盖,L2 测试缩短到秒级)
  - `_DETECT_DISABLED = os.environ.get("INFRA_DISABLE_DETECT") == "1"`:disabled 时 run_detection no-op,L2 手动调
- [x] 3.2 [impl] 新增 `backend/app/services/detect/judge.py`:
  - `DIMENSION_WEIGHTS: dict[str, float]`(合计 1.00;值按 design.md D4)
  - `def compute_report(pair_comparisons, overall_analyses) -> (total_score, risk_level)`
  - `async def judge_and_create_report(project_id, version, session)`:加载 pair + overall → compute → INSERT AnalysisReport + UPDATE project.status='completed' + broker publish `report_ready`
- [x] 3.3 [impl] 在 `backend/app/main.py` 的 FastAPI `lifespan` 中注册 startup 调 `scanner.scan_and_recover()`(阻塞完成)+ shutdown 调 `shutdown_cpu_executor()`

## 4. 后端服务层 — async_tasks tracker + scanner

- [x] 4.1 [impl] 新增 `backend/app/services/async_tasks/__init__.py`:空 __init__
- [x] 4.2 [impl] 新增 `backend/app/services/async_tasks/tracker.py`
- [x] 4.3 [impl] 新增 `backend/app/services/async_tasks/scanner.py`
- [x] 4.4 [impl] 改造 `backend/app/services/extract/engine.py`:`extract_archive` 外层 `async with track(subtype='extract')` 包裹
- [x] 4.5 [impl] 改造 `backend/app/services/parser/content/__init__.py`:`extract_content` 外层 `async with track(subtype='content_parse')` 包裹
- [x] 4.6 [impl] 改造 `backend/app/services/parser/llm/role_classifier.py`:`classify_bidder` 外层 `async with track(subtype='llm_classify')` 包裹

## 5. 后端路由 — analysis + reports

- [x] 5.1 [impl] 新增 `backend/app/api/routes/analysis.py`:POST start / GET status / GET events(SSE)
- [x] 5.2 [impl] 新增 `backend/app/api/routes/reports.py`:GET reports/{version} 骨架
- [x] 5.3 [impl] 改造 `backend/app/api/routes/projects.py`:GET /{id} 响应新增 `analysis` 字段
- [x] 5.4 [impl] 在 `backend/app/main.py` 注册 analysis + reports router(挂 `/api/projects` 前缀)

## 6. 后端 schema

- [x] 6.1 [impl] 新增 `backend/app/schemas/agent_task.py`:`AgentTaskResponse`
- [x] 6.2 [impl] 新增 `backend/app/schemas/analysis.py`:`AnalysisStartResponse / AnalysisStartConflictResponse / AnalysisStatusResponse`
- [x] 6.3 [impl] 新增 `backend/app/schemas/report.py`:`ReportDimension` + `ReportResponse`
- [x] 6.4 [impl] 改造 `backend/app/schemas/project.py`:`ProjectAnalysisSummary / ProjectAnalysisReport` + `ProjectDetailResponse.analysis`

## 7. 前端 — API + 类型

- [x] 7.1 [impl] 扩展 `frontend/src/types/index.ts`:`AgentTaskStatus / AgentType / AgentTask / AnalysisStartResponse / AnalysisStatusResponse / DetectEvent / RiskLevel / ReportResponse / ProjectAnalysisSummary` 等
- [x] 7.2 [impl] 扩展 `frontend/src/services/api.ts`:`startAnalysis / getAnalysisStatus / analysisEventsUrl / getReport`

## 8. 前端 — 组件 + hook + page

- [x] 8.1 [impl] 新增 `frontend/src/hooks/useDetectProgress.ts`
- [x] 8.2 [impl] 新增 `frontend/src/components/detect/StartDetectButton.tsx`
- [x] 8.3 [impl] 新增 `frontend/src/components/detect/DetectProgressIndicator.tsx`
- [x] 8.4 [impl] 新增 `frontend/src/pages/reports/ReportPage.tsx`(Tab1 骨架)
- [x] 8.5 [impl] 改造 `frontend/src/pages/projects/ProjectDetailPage.tsx`:集成 DetectSection
- [x] 8.6 [impl] 改造 `frontend/src/App.tsx`:注册 `/reports/:projectId/:version` 路由

## 9. 后端 L1 单元测试

- [x] 9.1 [L1] 新增 `backend/tests/unit/test_detect_registry.py`:10 Agent 注册表大小 + 7 pair + 3 global + 重复注册抛错 + get 未知 name 返 None
- [x] 9.2 [L1] 新增 `backend/tests/unit/test_detect_preflight.py`:text_similarity skip 场景 + error_consistency downgrade 场景 + preflight 异常视为 skip
- [x] 9.3 [L1] 新增 `backend/tests/unit/test_detect_engine.py`:单 Agent 成功 / 异常隔离 / 超时;full orchestrator 用 INFRA_DISABLE_DETECT + 手动调 run_detection;CPU_EXECUTOR lazy 初始化
- [x] 9.4 [L1] 新增 `backend/tests/unit/test_detect_judge.py`:compute_report 3 组(全 succeeded / 部分 skipped / 铁证强制 ≥85);权重合计 1.00
- [x] 9.5 [L1] 新增 `backend/tests/unit/test_async_tasks_tracker.py`:正常退出 / 异常重抛 / 心跳 UPDATE(用短间隔 + asyncio.sleep 验证)
- [x] 9.6 [L1] 新增 `backend/tests/unit/test_async_tasks_scanner.py`:空表 no-op / extract 恢复 / content_parse 恢复 / llm_classify 恢复 / agent_run 恢复 + 项目 status 回滚 / 单 handler 失败不影响其他

## 10. 前端 L1 组件测试

- [x] 10.1 [L1] 新增 `frontend/src/components/detect/__tests__/StartDetectButton.test.tsx`:各前置条件禁用 + hover tooltip + 点击调 startAnalysis + 409 处理
- [x] 10.2 [L1] 新增 `frontend/src/components/detect/__tests__/DetectProgressIndicator.test.tsx`:进度条渲染 + 一行摘要 + "查看报告"按钮
- [x] 10.3 [L1] 新增 `frontend/src/pages/reports/__tests__/ReportPage.test.tsx`:骨架渲染 + 风险等级徽章 + 铁证维度置顶 + 404 回退
- [x] 10.4 [L1] 新增 `frontend/src/hooks/__tests__/useDetectProgress.test.ts`:EventSource dispatch + onerror 切轮询 + onmessage 清 interval(mock EventSource)

## 11. 后端 L2 e2e 测试

- [x] 11.1 [L2] 扩展 `backend/tests/fixtures/auth_fixtures.py` 的 `clean_users`:按 FK 依赖顺序新增 5 张表清理 `async_tasks → analysis_reports → overall_analyses → pair_comparisons → agent_tasks`(在 bid_documents 前)
- [x] 11.2 [L2] 扩展 `backend/tests/fixtures/llm_mock.py`:预留 `mock_llm_judge_success / mock_llm_judge_timeout` fixture(C6 不用,C14 接入)
- [x] 11.3 [L2] 新增 `backend/tests/e2e/test_analysis_start_api.py`:覆盖 spec "启动检测 API" + "前置校验" + "幂等 409" 共 ~10 Scenario
- [x] 11.4 [L2] 新增 `backend/tests/e2e/test_analysis_status_api.py`:覆盖 spec "检测状态快照 API" 3 Scenario
- [x] 11.5 [L2] 新增 `backend/tests/e2e/test_analysis_sse_api.py`:覆盖 spec "SSE 检测事件流";用 httpx stream 消费;缩短 heartbeat 到 0.5s 避免 hang
- [x] 11.6 [L2] 新增 `backend/tests/e2e/test_reports_api.py`:覆盖 spec "报告骨架 API" 3 Scenario
- [x] 11.7 [L2] 新增 `backend/tests/e2e/test_detect_engine_orchestration.py`:覆盖 "Agent 并行调度"(INFRA_DISABLE_DETECT=0,直接调 run_detection,AGENT_TIMEOUT_S=0.1 / GLOBAL_TIMEOUT_S=2 缩短);验单 Agent 异常/超时/全部完成 → report 生成
- [x] 11.8 [L2] 新增 `backend/tests/e2e/test_detect_agents_dummy.py`:覆盖 "10 Agent 骨架 dummy run" 3 Scenario(pair 写 PairComparison / global 写 OverallAnalysis / 10 模块加载注册)
- [x] 11.9 [L2] 新增 `backend/tests/e2e/test_async_tasks_scanner_e2e.py`:覆盖 "async_tasks 通用任务表与重启恢复" 5 Scenario;手工 INSERT 过期 async_tasks 行 → 调 scan_and_recover → 验状态回滚
- [x] 11.10 [L2] 新增 `backend/tests/e2e/test_project_detail_with_analysis.py`:覆盖 project-mgmt MODIFIED 的 "analysis 字段 null / 已检测 / 列表 risk_level" 共 4 Scenario
- [x] 11.11 [L2] 命令验证:`pytest backend/tests/e2e/ -xvs` 全绿(C2/C3/C4/C5 不回归)

## 12. L3 UI e2e 测试

- [x] 12.1 [L3] 新增 `e2e/specs/c6-detect-framework.spec.ts`:启动检测 → SSE 进度条更新 → 报告骨架页面;用 `page.route` 拦截 analysis/events(若可行)
- [x] 12.2 [L3] 命令验证:`npm run e2e`;若 Docker Desktop kernel-lock 未解除 → 降级手工凭证
- [x] 12.3 [L3] 若降级:在 `e2e/artifacts/c6-2026-04-14/README.md` 写 demo flow + 7 张截图约定(启动按钮 / 进度条中途 / Agent 完成摘要 / 报告骨架 / 风险徽章 / 维度列表 / LLM 占位卡片)

## 13. 文档联动

- [x] 13.1 [manual] 更新 `backend/README.md`:新增 "C6 detect-framework 依赖" 段:`INFRA_DISABLE_DETECT` 环境变量 + `AGENT_TIMEOUT_S / GLOBAL_TIMEOUT_S` 覆盖机制 + SSE 路径 `/analysis/events` + 启动扫描 scanner 行为
- [x] 13.2 [manual] 更新 `docs/handoff.md`:§1 状态(M3 启动,C6 实施完)/ §2 本次 session 决策(A1/B1/C2/D3 + apply 阶段就地敲定)/ §3 follow-up 清理(C4/C5 event loop 遗留已消化)/ §5 最近变更历史追加 C6 归档条目

## 14. 总汇

- [x] 14.1 跑 [L1][L2][L3] 全部测试,全绿
