# Tasks

> **CLAUDE.md 例外说明**:本 change 属"孤立改配置"例外(仅同步 archive 漏的迁移),无 [L2]/[L3] 业务流测试;保留 1 条 [L1] 钉默认值,1 条 [manual] 重跑 e2e 项目 2486 验证报价回填恢复。

## 1. 改 `llm_timeout_s` 默认值与文档同步

- [x] 1.1 [impl] 改 `backend/app/core/config.py::Settings.llm_timeout_s` 默认 `30.0` → `300.0`,docstring 写清"per-call 与 cap 现在共用 300;`min(per_call, cap)` 实际生效;想快失败请 admin/llm UI 配 timeout 或 env LLM_TIMEOUT_S=N"
- [x] 1.2 [impl] 改 `backend/.env.example`:删 / 改老的 `LLM_CALL_TIMEOUT` 误导注释,新注释讲清两个变量并联走 min 的关系,默认都是 300
- [x] 1.3 [impl] 改 `docker-compose.yml::LLM_TIMEOUT_S` 默认值 `${LLM_TIMEOUT_S:-30}` → `${LLM_TIMEOUT_S:-300}`(test compose 不动)
- [x] 1.4 [impl] 删 `backend/.env` 里的 `LLM_TIMEOUT_S=60` 那一行(本机配置,让代码默认生效)

## 2. L1 测试钉 per-call 默认值

- [x] 2.1 [L1] `backend/tests/unit/test_llm_timeout_default.py` 加一条:
  - case: `Settings(_env_file=None).llm_timeout_s == 300.0`(防未来误改回 30)
  - 既有 `llm_call_timeout == 300.0` 测试保留

## 3. Manual e2e 验证报价回填恢复

- [x] 3.1 [manual] 重启后端;对项目 2486 调 `POST /api/projects/2486/parse-progress/reparse` 或等价的 re-parse 接口
- [x] 3.2 [manual] 验证终态:
  - 3 个 bidder(2778/2779/2780) parse_status 从 `price_failed` → `priced` / `partial`
  - `price_parsing_rules.status` 从 `failed` → `confirmed`,`sheets_config` 非空
  - 跑 `POST /api/projects/2486/analysis/start` 启动新一轮检测,等完成后看报告:报价 3 维度(price_consistency / price_anomaly / price_near_ceiling)有得分(非 skipped)
- [x] 3.3 [manual] 凭证落盘 `e2e/artifacts/fix-llm-timeout-default-followup-2026-04-26/`:
  - `README.md`:执行步骤 + 期望结果 + 实际结果对照
  - `before_state.json`:re-parse 前 bidder + price_parsing_rule 状态 dump(从这次跑的 backend.log 截取或 DB query)
  - `after_state.json`:re-parse 后 + 新一轮检测后的状态
  - 报告页截图(总览 + 维度明细),对比"报价 3 维度从 skipped 变有分"

## 4. Spec 同步

- [x] 4.1 [impl] 本 change `specs/pipeline-error-handling/spec.md` delta 已写入;archive 时 merge 进 `openspec/specs/pipeline-error-handling/spec.md`,本任务仅确认 delta 内容无误

## 5. 全量测试 + 归档准备

- [x] 5.1 跑 [L1][L2][L3] 全部测试,全绿
  - L1(backend):`pytest backend/tests/unit/` → **1163 passed, 8 skipped**(新增 2 case:test_llm_timeout_s_default_is_300 + test_llm_timeout_s_env_override)✅
  - L1(frontend):本 change 无前端改动,沿用既有绿态(无新增 / 修改前端测试)
  - L2:`TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55432/documentcheck_test pytest tests/e2e/` → **286 passed, 2 skipped**(161s)✅
  - L3:本 change 纯配置/启动行为,无 UI 变化,L3 不跑(CLAUDE.md 孤立配置例外条款)
  - 凭证:`e2e/artifacts/fix-llm-timeout-default-followup-2026-04-26/`(README + before/after_state.json + comparison.json)

## 6. 归档前 self-check

- [x] 6.1 `openspec validate fix-llm-timeout-default-followup --strict` → "is valid"
- [x] 6.2 `git diff` 确认:只改了 config.py(<5 行)+ .env.example + docker-compose.yml(1 行)+ backend/.env(删 1 行,gitignore 不进版本)+ test_llm_timeout_default.py(加 case)+ 新 change 目录 + 新 artifacts 目录
- [x] 6.3 `handoff.md` 追加本次归档条目(最近 5 条保留策略;archive `config-llm-timeout-default` 仍在,本次条目说明"补 archive 漏的同步迁移")
