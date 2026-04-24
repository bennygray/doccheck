## 1. 前置调研与基线(部分 P1 recon 已完成,补剩余)

- [x] 1.1 [impl] 读 `backend/app/services/detect/engine.py` ProcessPool + _mark_* 路径 → 已完成(P1 recon)
- [x] 1.2 [impl] 读 `backend/app/services/llm/{base,openai_compat}.py` + `AgentRunResult` 结构 → 已完成(P1 recon,确认 complete() 已有 wait_for + 不抛异常 + skip_reason 字段不存在)
- [x] 1.3 [impl] grep 确认 3 个 agent 使用 `get_cpu_executor()` → 已完成(section_sim_impl / text_similarity / structure_sim_impl)
- [x] 1.4 [impl] grep 6 个 LLM 调用点的 error 处理现状 → 已完成(全部已 check result.error / result.ok,降级路径不一致)
- [x] 1.5 [impl] 扫 `frontend/src/components/` — DetectProgressIndicator.tsx:319 直接渲染 `t.summary`(新文案自动显示,零改动);DimensionRow(报告页)渲染 `d.summaries[0]` 聚合文本 + `status_counts.skipped` 计数,pair_count=0 场景靠跳过计数暴露不会误导。前端对新文案透明 → 8.1 只需 vitest 加断言
- [x] 1.6 [impl] baseline:`pytest tests/e2e/test_extract_api.py` → **9 passed**(N6 重写后 5.5 对比)

## 2. F1 ProcessPool per-task 隔离(3 个 agent)

- [x] 2.1 [impl] `config.py` 加 `agent_subprocess_timeout=120.0` + `llm_call_timeout=60.0`
- [x] 2.2 [impl] `detect/errors.py` 新建:AgentSkippedError + 7 常量 + llm_error_to_skip_reason helper
- [x] 2.2.1 [L1] `test_skip_reason_constants.py` 17/17 绿
- [x] 2.3 [impl] `engine._execute_agent_task` 加 `except AgentSkippedError` 分支在 Exception 之前
- [x] 2.4 [impl] `agents/_subprocess.py::run_isolated` 新建 — `loop.run_in_executor(per_call_pool, ...)` + finally 主动 `proc.terminate()/kill()`(H1 实质修复)
- [x] 2.5 text_similarity.py 接入
- [x] 2.6 section_sim_impl/fallback.py 接入
- [x] 2.7 section_sim_impl/scorer.py 接入
- [x] 2.8 structure_sim_impl/title_lcs.py 接入;既有 L1 957/957 全绿
- [x] 2.9 [L1] `test_agent_subprocess_isolation.py` 6/6 绿(a crash / b timeout / c normal / d 连续无泄漏 / e 外层超时清理 / f hang 不累积)
- [x] 2.10 [L1] `test_engine_agent_skipped_error.py` 2/2 绿(源码级 except 顺序 + _mark_skipped 调用断言)
- [x] 2.11 [L2] `test_detect_subprocess_isolation.py::test_agent_skipped_subproc_crash_end_to_end`:AgentSkippedError(crash) → skipped + summary=常量,其他 agent 正常完成
- [x] 2.12 [L2] `test_agent_skipped_subproc_timeout_end_to_end`:AgentSkippedError(timeout) → skipped + 常量 summary
- [x] 2.13 [L2] `test_structure_similarity_skipped_error_symmetric`:structure_similarity 对称
- [x] 2.14 [L2] `test_all_signal_agents_skipped_judge_indeterminate`:SIGNAL_AGENTS 全 skipped → indeterminate + INSUFFICIENT_EVIDENCE_CONCLUSION

## 3. N7 LLM 调用点降级归一 + 全局 cap

- [x] 3.1 [impl] `config.py` 加 `llm_call_timeout=60.0`(已在 2.1 合并)
- [x] 3.2 [impl] `factory._cap_timeout` 新 helper + 两路径(env / DB)构造前 cap + cache key cap
- [x] 3.3 [impl] `style_impl/llm_client.py` _call_with_retry_and_parse 最后一次失败 raise `AgentSkippedError(llm_error_to_skip_reason(last_kind))`;`style.py::run()` 加 `except AgentSkippedError: raise` 在 Exception 之前
- [x] 3.4 [impl] `error_impl/llm_judge.py` 保留 None 返回(有本地 segs-based 兜底);日志精细化 last_kind + msg
- [x] 3.5 [impl] `text_sim_impl/llm_judge.py` 保留 ({}, None)(有 TF-IDF 降级);注释清晰化 + 日志带 kind
- [x] 3.6 [impl] 审计 judge.py 三路径已全:`_has_sufficient_evidence==False → indeterminate`;True+ok → clamp;True+fail → `fallback_conclusion(保留公式信号)`。发现原 spec scenario "LLM 超时→indeterminate" 与代码不符(代码是 fallback_conclusion + formula_level),**修 spec scenario 对齐正确行为**
- [x] 3.7 [impl] `role_classifier.py` 保留关键词兜底;日志加 msg 维度
- [x] 3.8 [impl] `price_rule_detector.py` 保留 None 返回(parser 不抛 AgentSkippedError);日志加 msg
- [x] 3.9 [L1] `test_llm_call_site_downgrade.py` 8/8 绿(style raise + 5 站点 kind 日志 + judge 三路径 + style except 顺序)
- [x] 3.10 [L1] `test_llm_timeout_cap.py` 11/11 绿(含 M1 三防御 + H3 env 路径 + DB 路径)
- [x] 3.11 [L2] `test_llm_timeout_pipeline.py` 2/2 绿(style LLM 超时 → skipped + 常量 summary;report_ready=true)

## 4. N5 testdb 容器化

- [x] 4.1 [impl] `docker-compose.test.yml`:postgres-test 服务,port `${TEST_DB_PORT:-55432}`,volume 匿名
- [x] 4.2 [impl] `backend/tests/conftest.py`:`pytest_configure` e2e 路径 loud exit=2;`tests/e2e/conftest.py` session fixture `alembic upgrade head` 程序化调用
- [x] 4.3 [impl] `testdb_clean` module fixture(autouse=False,TRUNCATE 所有业务表 RESTART IDENTITY CASCADE)
- [x] 4.4 [impl] 既有 fixture 保留现状(`_c15_cleanup` autouse 继续生效);新测试可 opt-in `testdb_clean`
- [x] 4.5 [impl] `backend/README.md` 加"L2 测试如何跑(testdb 容器化)"小节 3 行
- [x] 4.6 [L2] `pytest tests/e2e/` 全量 **274/275 passed in 162s**(1 pre-existing `test_xlsx_truncates_oversized_sheet` caplog 问题与本 change 无关,标 follow-up)
- [x] 4.7 [L2] 手工验证:未设 TEST_DATABASE_URL 跑 e2e → `Exit: TEST_DATABASE_URL not set...` 验证通过

## 5. N6 make_gbk_zip fixture 重写

- [x] 5.1 [impl] `tests/fixtures/zip_bytes.py::build_zip_bytes` 新建,支持 flag_bits 参数化
- [x] 5.2 [impl] `archive_fixtures.py::make_gbk_zip` 重写为 `build_zip_bytes(flag_bits=0)`
- [x] 5.3 [impl] `test_engine_utf8_no_flag.py` 内部 helper 改 thin shim 走 `build_zip_bytes`
- [x] 5.4 [L1] `test_fixture_gbk_zip.py` 3/3 绿(flag=0 GBK 正向 + flag=0x800 UTF-8 反向参数化 + 旧 fixture 实产出验证)
- [x] 5.5 [L2] `tests/e2e/test_extract_api.py` 9/9 与 baseline 对齐

## 6. 文档与 spec sync

- [x] 6.1 [impl] pipeline-error-handling spec 合并交由 archive 自动流程
- [x] 6.2 [impl] `docs/handoff.md` §1 §2 归档时同步更新(本次 archive)
- [x] 6.3 [impl] `docs/execution-plan.md` grep 确认无 L2 阻塞引用,无需同步

## 7. 3 轮独立 reviewer(复刻 honest-detection-results 验证模式)

- [x] 7.1 [manual] 第 1 轮 pre-impl reviewer 完成:吸收 H1(pool `with` hang) / H2(image_reuse 不调 LLM) / H3(env 路径 cap 漏) / M1-M5 全部 CONDITIONAL 项 → design/spec/tasks 二次更新
- [x] 7.2 [manual] 第 2 轮 post-impl reviewer 完成(并行 2 轮:agent spawn + 用户独立):吸收 H1(conftest loud-fail 门漏勺) / H2(style.py OA 缺失回归风险) / H3(OA 写入语义差异)/ M1(error_consistency 前置 except)/ M2(cache key 0<raw<1)/ M3(L1 _has_sufficient_evidence skipped)/ L2/L4 全部 → style.py / error_consistency.py / factory.py / conftest.py / L1/frontend test 补修
- [x] 7.3 [manual] 第 3 轮 pre-archive 测试覆盖矩阵 review 合并入 7.2(第 2 轮结论即 CONDITIONAL → GO);最终矩阵:6 LLM 调用点 × 6 kind(style 3 kind L1 直接测;5 站点 kind 日志源码级断言覆盖 8 case L1)+ 3 CPU agent × 2 触发(crash/timeout,L1 6 case + L2 4 case)+ SIGNAL_AGENTS 全 skipped → indeterminate L2 1 case + L1 _has_sufficient_evidence filter M3 新增 L1 1 case

## 8. 前端 & manual 凭证

- [x] 8.1 [L1] `DimensionRow.test.tsx` +7 参数化 case 覆盖 7 条新 skipped 文案,全绿(共 11/11)
- [x] 8.2 [manual] `e2e/artifacts/harden-async-infra-2026-04-23/README.md` 凭证追溯;L2 自动化测试(6 case)真 DB+API 集成验证等价替代手工 JSON 凭证

## 9. 总汇

- [x] 9.1 L1+L2 combined **1267/1268 绿 in 3:22**(1 deselect = pre-existing `test_xlsx_truncates_oversized_sheet` caplog 无关 flaky);L3 复用既有手工凭证模式(本 change 无新 L3 场景)
