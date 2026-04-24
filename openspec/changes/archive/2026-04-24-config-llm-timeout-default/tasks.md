# Tasks

> **CLAUDE.md 例外说明**:本 change 属 "孤立改配置" 例外(仅改默认值 + lifespan 1 处 reconfigure 兜底),无 [L2]/[L3] 业务流测试;保留 1 条 [L1] 元测试钉默认值防 regression,proposal.md 已说明。

## 1. 改 `llm_call_timeout` 默认值 60→300

- [x] 1.1 [impl] 改 `backend/app/core/config.py::Settings.llm_call_timeout` 默认值 `60.0` → `300.0`,docstring / inline comment 同步说明理由(ark-code-latest 实测 ~132s + buffer)
- [x] 1.2 [impl] `backend/.env.example` 若有 `LLM_CALL_TIMEOUT` 示例,同步示例值到 300(或保留 env 覆盖示例的说明)

## 2. Windows 控制台 UTF-8 兜底

- [x] 2.1 [impl] `backend/app/main.py` lifespan 顶部(tracker 启动之前)加 try/except 包裹的 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` + `sys.stderr.reconfigure(...)`,AttributeError/ValueError 兜底(对应 spec scenario "stdout 已被测试框架替换")
- [x] 2.2 [impl] 如 lifespan 已有前置 setLevel(app logger)代码,reconfigure 放在其之前

## 3. 测试(L1 一条钉默认值)

- [x] 3.1 [L1] 新建 `backend/tests/unit/test_llm_timeout_default.py`:
  - case 1: `Settings(_env_file=None)` 的 `llm_call_timeout == 300.0`(防未来误改回 60)✓
  - case 2: `LLM_CALL_TIMEOUT` env 覆盖生效(设 env=60 → Settings 读到 60)✓

## 4. Spec 同步

- [x] 4.1 [impl] 本 change `specs/pipeline-error-handling/spec.md` delta 已写入;archive 时会 merge 进 `openspec/specs/pipeline-error-handling/spec.md`,本任务仅确认 delta 内容无误

## 5. 全量测试 + 归档准备

- [x] 5.1 跑 [L1][L2][L3] 全部测试,全绿
  - L1(backend):1022 passed / 5 skipped ✓
  - L1(frontend):114 passed ✓
  - L2:281 passed ✓(testdb 容器 localhost:55432)
  - L3:本 change 纯配置/启动行为,无 UI 变化,L3 不跑(CLAUDE.md 孤立配置例外条款)
- [x] 5.2 手动起 backend 验证 Windows lifespan reconfigure 不报错 ✓
  - 凭证:`e2e/artifacts/config-llm-timeout-default-2026-04-24/`(backend_startup.log + health.json + README)
  - 启动干净无 UnicodeEncodeError;对照 2026-04-24 project 1728 日志中该 error 已消失

## 6. 归档前 self-check

- [x] 6.1 openspec validate config-llm-timeout-default → "is valid" ✓
- [x] 6.2 `git diff` 确认:只改了 config.py(4 行) + main.py(13 行 lifespan + import sys) + .env.example(3 行) + 新 test 文件 + 新 change dir + 新 artifacts dir ✓
- [x] 6.3 handoff.md 追加本次归档条目(最近 5 条保留策略)✓ section 2 重写 + section 5 新增条目 + 移除 agent-skipped-error-guard(保留 5 条)
