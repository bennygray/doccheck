## Why

前 3 次 change 累积了 5 项测试/诊断基础设施层面的 follow-up:

- **harden-async-infra** 的 reviewer 明确标过 2 项 latent risk(`run_isolated` 的 `pool._processes` 下划线依赖 + `test_engine_except_order` 的正则去注释脆弱),agent-skipped-error-guard 已用 AST 升级了元测试但 engine 层 except 顺序断言没跟着改;`pool._processes` 一直没处理,Py 3.14+ 潜在债
- **clean testdb 全量跑**暴露 1 项 **real bug**:`test_xlsx_truncates_oversized_sheet` 的 caplog 不捕获 warning。recon 锁定根因 = `alembic/env.py:27` 的 `fileConfig()` 默认 `disable_existing_loggers=True`,在 L2 session fixture `alembic upgrade head` 跑时 **disable 了所有 `app.*` logger**(alembic.ini 白名单只有 root/sqlalchemy/alembic)。下一次类 N3 诊断或新 caplog 测试都会撞上
- **llm-classifier-observability** 观察到 uvicorn `--log-level info` 不级联到 `app.*` logger,N3 采样的 info 日志未能取到,只能靠 DB + warning 缺席反向推导;handoff 建议"并入下一个触碰 main.py 的 change"
- **honest-detection-results** 遗留 `text_similarity _DEGRADED_SUMMARY` 前端 evidence_json 消费没端到端断言,UI 降级文案随改动回归无测试网

5 项性质同属"**前序 hardening 的遗留 + 测试/诊断基础设施可靠性**",逐个单改 ceremony 成本 5×,合 1 个 change 一次归档。零产品行为变化。

## What Changes

1. **Item 1(🔴 real bug)**:`backend/alembic/env.py:27` 的 `fileConfig(config.config_file_name)` 加 `disable_existing_loggers=False` 参数 —— 阻止 L2 session fixture 意外 disable `app.*` logger,修复 `test_xlsx_truncates_oversized_sheet` caplog 丢警告 bug。L1 加显式回归断言(alembic upgrade head 后 `app.services.parser.content` 等关键 logger `.disabled is False`)
2. **Item 2(🟡 latent)**:`backend/tests/unit/test_engine_agent_skipped_error.py` 的 engine 层 `_execute_agent_task` except 顺序断言从正则 + `_extract_code_lines` 去注释升级为 AST visitor,复用 `test_agent_except_skipped_guard.py` 已落地的 pattern。正则方案 harden-async-infra reviewer 标过不处理字符串字面量里的 `#`
3. **Item 3(🟡 latent)**:`backend/app/services/detect/agents/_subprocess.py::run_isolated` 的 finally 块 `getattr(pool, "_processes", {}).values()` 改 try/except + fallback,future-proof Py 3.14+ stdlib 潜在移除/重命名。fallback 路径 = 纯 `shutdown(wait=False, cancel_futures=True)`,不尝试主动 terminate/kill。L1 加 sanity test 验 `_processes` 为空或缺失时 run_isolated 不崩
4. **Item 4(🟡 诊断盲区)**:`backend/app/main.py` lifespan 顶部加 `logging.getLogger("app").setLevel(logging.INFO)`(try/except 包裹失败不阻塞启动)—— 让 uvicorn 启动时 `app.*` logger 树级 INFO,未来 N3 类诊断 info 日志自然可见。L1 加启动后 app logger level 断言
5. **Item 6(🟢 覆盖空白)**:`frontend/src/components/DimensionRow.test.tsx` 补 text_sim `_DEGRADED_SUMMARY` 真实 evidence_json shape render 断言(`score_breakdown` 完整字段,而非 mock stub),防降级文案回归
6. **文档清理**:`docs/handoff.md` L97 stale "agent 全仓防御 except AgentSkippedError" 一行删除(agent-skipped-error-guard change 已落地并加了 AST 元测试强制,follow-up 项已消)

## Capabilities

### New Capabilities
(无)

### Modified Capabilities
(无 —— 零产品行为变化,零 spec 级 Requirement 改动。参照 llm-classifier-observability 先例:若 openspec validate 强制至少 1 delta,写一条**最小 ADDED** "测试基础设施鲁棒性" 契约 Requirement 到 `pipeline-error-handling` spec,锁 3 个**稳定**点:alembic fileConfig 白名单、run_isolated future-proof 兜底、engine except 顺序 AST 元测试强制。细节 / 字段阈值留 design)

## Impact

**后端代码**(4 个文件)
- `backend/alembic/env.py`:1 行参数
- `backend/app/services/detect/agents/_subprocess.py`:`run_isolated` finally 块 getattr → try/except(5-10 行)
- `backend/app/main.py`:lifespan 顶部 3-5 行(try/except + setLevel)
- `backend/tests/unit/test_engine_agent_skipped_error.py`:重写 engine 层 except 顺序断言为 AST visitor(改 30-50 行)

**前端代码**(1 个文件)
- `frontend/src/components/DimensionRow.test.tsx`:+1 case(真实 evidence_json render)

**新增 L1 测试**
- `test_alembic_preserves_app_loggers.py`(Item 1 回归)
- `test_run_isolated_future_proof.py`(Item 3 sanity)
- `test_main_lifespan_sets_app_log_level.py`(Item 4 断言)

**spec 改动**:若 openspec validate 强制,加 `pipeline-error-handling` 1 ADDED Requirement(最小)。否则不动。

**新增 artifacts**:无(本 change 纯代码 + 测试,不产 e2e/artifacts)。

**无 breaking change,无 DB/API/前端 route 变更**。Item 1 的 alembic 改动对 prod 迁移天然安全(严格更宽松)。Rollback 直接回滚 commit。
