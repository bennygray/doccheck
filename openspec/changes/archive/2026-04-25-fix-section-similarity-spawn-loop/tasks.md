# Tasks

> **CLAUDE.md 测试标准**:本 change 改 agent 实现热点(scorer 内部 spawn 循环),非孤立配置,要走完整 [L1] + [manual e2e] 验证。L2 沿用既有(mock LLM 不走真 spawn 路径,行为不变),L3 不跑(无 UI 改动)。

## 1. 实现批量化 helper + 替换 scorer for 循环

- [x] 1.1 [impl] 在 `backend/app/services/detect/agents/section_sim_impl/scorer.py` 加 module-level 函数 `compute_all_pair_sims_batch(chapter_pair_data, threshold, max_pairs) -> list[list[ParaPair]]`,内部循环调 `c7_tfidf.compute_pair_similarity`(子进程内单次执行 N 个章节对)
- [x] 1.2 [impl] 改 `scorer.score_all_chapter_pairs` 第 58-70 行的 for 循环:
  - 把 N 个 `(ca.paragraphs, cb.paragraphs)` 收集成 `chapter_pair_data` 列表
  - 替换成**一次** `await run_isolated(compute_all_pair_sims_batch, chapter_pair_data, threshold, max_pairs_to_llm, timeout=settings.agent_subprocess_timeout)`
  - 把返回的 `list[list[ParaPair]]` 直接赋给 `per_chapter_pairs`
- [x] 1.3 [impl] 确认 import 链:scorer.py 顶部加 `from app.services.detect.agents._subprocess import run_isolated` 和 `from app.core.config import settings`(原本是函数内 lazy import,现在出 for 循环,可放顶部减少噪音 — 但若有循环 import 风险则保持现状)

## 2. L1 测试钉批量化契约

- [x] 2.1 [L1] 新建 `backend/tests/unit/test_section_scorer_batch.py`,2 个 case:
  - `test_batch_helper_results_equivalent_to_per_pair`:用合成段落数据构造 3 个章节对,分别跑 `compute_all_pair_sims_batch` 和原始 N 次单调 `c7_tfidf.compute_pair_similarity`,断言 ParaPair 列表逐项 `(a_idx, b_idx, sim)` 相等
  - `test_scorer_calls_run_isolated_exactly_once`:monkeypatch `run_isolated` 替换为计数 fake;调用 `scorer.score_all_chapter_pairs` 用 5 个章节对的 fixture;断言 `call_counter == 1`(**核心防回归契约**)

## 3. Manual e2e 验证 section_similarity 跳出 timeout

- [x] 3.1 [manual] 重启 backend(`uv run uvicorn app.main:app --port 8001`),验证新代码 import 成功
- [x] 3.2 [manual] 通过 UI / API 新建项目 + 上传 3 供应商 zip(投标文件模板 2)+ 等解析完成 + 启动检测
- [x] 3.3 [manual] 等检测完成,验证终态:
  - `agent_tasks` 表 `agent_name='section_similarity'` 三个 pair 的 `status` 全为 `succeeded`(此前 v1/v2 均 timeout)
  - 单 pair 的 `elapsed_ms` < 60000(实测期望 30~55s)
  - `pair_comparisons.dimension='section_similarity'` 三行写入,evidence_json 含 chapter_pairs 数组
- [x] 3.4 [manual] 凭证落 `e2e/artifacts/fix-section-similarity-spawn-loop-2026-04-26/`:
  - `README.md`:执行步骤 + 期望 vs 实际 + before/after section_similarity 状态对比
  - `agent_tasks_after.json`:新一轮检测的 25 个 agent_task 状态 dump

## 4. Spec 同步

- [x] 4.1 [impl] 本 change `specs/pipeline-error-handling/spec.md` delta 已写入(MODIFIED Requirement "ProcessPool per-task 进程隔离" 加 1 scenario);archive 时 merge 进 `openspec/specs/pipeline-error-handling/spec.md`,本任务仅确认 delta 内容无误

## 5. 全量测试 + 归档准备

- [x] 5.1 跑 [L1][L2][L3] 全部测试,全绿
  - L1(backend):`pytest backend/tests/unit/` → **1166 passed, 8 skipped**(新增 3 case:核心契约 + 等价性 + 空边界,实际比 tasks 草稿多写了 1 个边界 case)✅
  - L1(frontend):本 change 无前端改动,沿用既有绿态
  - L2:`TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/documentcheck_test pytest tests/e2e/` → **286 passed, 2 skipped**(145s)✅
  - L3:本 change 无 UI 改动,L3 不跑(沿用 fix-llm-timeout-default-followup 同等论证)
  - 凭证:`e2e/artifacts/fix-section-similarity-spawn-loop-2026-04-26/`(README + agent_tasks_after.json)

## 6. 归档前 self-check

- [x] 6.1 `openspec validate fix-section-similarity-spawn-loop --strict` → "is valid"
- [x] 6.2 `git diff` 确认:只改了 `scorer.py`(~25 行)+ 新 L1 测试文件 + 新 change 目录 + 新 artifacts 目录
- [x] 6.3 `docs/handoff.md` 追加本次归档条目(最近 5 条保留策略)
