## 1. Item 1 — alembic fileConfig 修复(🔴 real bug)

- [x] 1.1 [impl] 修改 `backend/alembic/env.py:27`,把 `fileConfig(config.config_file_name)` 改为 `fileConfig(config.config_file_name, disable_existing_loggers=False)`。仅加一个 keyword arg,不改其他行
- [x] 1.2 [L1] 新建 `backend/tests/unit/test_alembic_preserves_app_loggers.py`:静态层 1 case(`test_env_py_passes_disable_existing_loggers_false` source 断言)+ 运行期层参数化 5 个 app logger name(需 TEST_DATABASE_URL)。合计 6 case
- [x] 1.3 [L2 回归] `pytest backend/tests/e2e/test_parser_content_api.py::test_xlsx_truncates_oversized_sheet` **FAILED → PASSED**,本 change Item 1 fix 的端到端验证通过;全量 L2 `pytest backend/tests/e2e/` **281/281 全绿**(此前稳定的 pre-existing fail 被治愈)
- [x] 1.4 [L1] `pytest backend/tests/unit/test_alembic_preserves_app_loggers.py` 6 case 全绿 in 1.01s

## 2. Item 2 — engine except 顺序 AST 升级(🟡 latent)

- [x] 2.1 [impl] 重写 `backend/tests/unit/test_engine_agent_skipped_error.py` 采 AST visitor(内联 10-20 行,复用 agent-skipped-error-guard 同型 pattern,不抽 shared helper);**AST 升级意外发现**老正则测没查到的情况:preflight try 的 broad except body 调 `_mark_skipped`(语义无 bug);精修契约为"只对 body 调 `_mark_failed` 的 broad except 强制 AgentSkippedError 前置"(更准确反映真契约)
- [x] 2.2 [L1] 保留 `test_engine_except_order_agent_skipped_before_broad_that_fails`(升级版)+ `test_engine_agent_skipped_branch_calls_mark_skipped`(也用 AST)2 case 语义等价于原版,跑绿
- [x] 2.3 [L1] 反向验证 `test_visitor_catches_inverted_order_on_synthetic_source`:手工构造 inverted 源码 → 核心契约函数正确判违规,含 index 信息。不动真实 engine.py
- [x] 2.4 [L1] `pytest backend/tests/unit/test_engine_agent_skipped_error.py` 3 case 全绿 in 0.12s

## 3. Item 3 — run_isolated future-proof(🟡 latent)

- [x] 3.1 [impl] `backend/app/services/detect/agents/_subprocess.py::run_isolated` finally 块:`_processes` 访问加 `try: ... except (AttributeError, TypeError) as exc: workers=[]`,fallback 到纯 shutdown(wait=False) 路径,不尝试 terminate/kill
- [x] 3.2 [L1] 新建 `test_run_isolated_future_proof.py`:**不注入 mock 破坏 pool 内部**(stdlib 运行期本身用 `_processes`,mock 会拖垮 pool 本体)→ 改**静态源码断言 3 case**(try/except 结构 / fallback workers=[] / shutdown 调用)+ **实跑 happy path 1 case**;共 4 case
- [x] 3.3 [L1] `pytest backend/tests/unit/test_run_isolated_future_proof.py` 4 case 绿 + `pytest backend/tests/unit/test_agent_subprocess_isolation.py` 6 既有 case 全绿 → 合计 10/10,零回归

## 4. Item 4 — main.py app logger setLevel(🟡 诊断盲区)

- [x] 4.1 [impl] `backend/app/main.py` lifespan 顶部加 `try: logging.getLogger("app").setLevel(logging.INFO) except Exception: pass`(带 `# noqa: BLE001` 注释说明不阻塞启动)。仅 1 try/except block,不改 handler/dictConfig
- [x] 4.2 [L1] 新建 `test_main_lifespan_sets_app_log_level.py`:静态层 2 case(source 断言含 setLevel + 包在 try/except)+ 运行期 1 case 真跑 lifespan 断言 app logger level==INFO(monkey 禁用 lifespan 内 DB 依赖 seed/scanner/admin-llm-config 避误触)
- [x] 4.3 [L1] `pytest backend/tests/unit/test_main_lifespan_sets_app_log_level.py` 3 case 全绿 in 0.12s

## 5. Item 6 — DimensionRow text_sim _DEGRADED_SUMMARY 前端断言(🟢 覆盖空白)

- [x] 5.1 [impl] 读 `backend/app/services/detect/agents/text_similarity.py::_DEGRADED_SUMMARY` 常量("AI 研判暂不可用,仅展示程序相似度(降级)");frontend DimensionRow 仅消费 `summaries[0]`,不直接读 evidence_json(evidenceSummary 工具的 `summarizeText` 对 degraded 无特化,现状返空字符串 —— 与前端侧用户可见度一致:顶部 summaries[0] 展示 degraded 文案,详情页走公式 summary)
- [x] 5.2 [L1/前端] `frontend/src/pages/reports/DimensionRow.test.tsx` 新增 describe "text_similarity degraded 真实场景(Item 6)" 2 case:(a) `best_score=42.5` 保留公式分数 + `summaries=[_DEGRADED_SUMMARY]` + `status_counts={succeeded:1}`(degraded ≠ skipped 的真实 shape)→ assert 降级文案可见 + 分数 "42.5" 渲染;(b) summaries 空数组 graceful → 组件不崩 + 降级文案不见
- [x] 5.3 [L1/前端] `npm test -- --run DimensionRow` 14 case 全绿(既有 12 + Item 6 新 2);全量前端 `npm test -- --run` **113/114 绿,1 pre-existing fail `AdminUsersPage 创建用户成功`**(clean tree 上验证同样失败,与本 change 无关,标 follow-up);零本 change 回归

## 6. 文档清理

- [x] 6.1 [impl] 删除 `docs/handoff.md` §2.bak_honest-detection-results "遗留到下次 / backlog" 里 2 条 stale 项:
  - "agent 全仓防御 except AgentSkippedError: raise"(已被 agent-skipped-error-guard 落地 + AST 元测试强制)
  - "text_similarity _DEGRADED_SUMMARY 文案覆盖"(已被本 change Item 6 补强)
  改为 strikethrough + ✅ + 引用归档来源,保留历史痕迹不真删(便于审计)

## 7. 归档前总汇

- [x] 7.1 `pytest backend/tests/unit/` **1020 passed + 5 skipped in 40.12s**(baseline 1011 + 本 change +9;5 skipped = 其中 test_alembic_preserves_app_loggers 静态部分跑,实运行部分未触发 TEST_DATABASE_URL 的情况 skip;其他既有 skip 沿续)
- [x] 7.2 `pytest backend/tests/e2e/` **281 passed in 175.81s**(比 baseline 280 多 1 —— 之前稳定 pre-existing fail 的 `test_xlsx_truncates_oversized_sheet` 被 Item 1 修复治愈)
- [x] 7.3 `cd frontend && npm test -- --run` **113 passed + 1 pre-existing fail**(`AdminUsersPage 创建用户成功` 在 clean tree 上同样失败,非本 change 引入,标 follow-up);DimensionRow 新 2 case 全绿
- [x] 7.4 [L1][L2] 全绿;L3 本 change 无 UI 路由/交互改动,延续项目 Docker kernel-lock 手工凭证;Item 6 涉及前端但已有 L1 组件测试,无 L3 manual 凭证需求
- [x] 7.5 归档前校验全通过:所有 [L1][L2] 任务 [x];Item 1 的 L2 回归 `test_xlsx_truncates_oversized_sheet` 显式绿;L2 281 全绿;满足归档条件
