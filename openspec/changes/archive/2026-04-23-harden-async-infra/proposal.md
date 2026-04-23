## Why

上一轮 `honest-detection-results` 归档时遗留 4 条基础设施鲁棒性问题(F1/N5/N6/N7)。P1 代码调研(2026-04-23)发现:
- **F1 真实风险放大**:共享 `get_cpu_executor()` 被 **3 个** agent(`section_similarity` / `text_similarity` / `structure_similarity`)使用,任一份坏 docx 段错误 / OOM 会把整池拉崩,本轮所有投标人这 3 个维度全失败。
- **N7 诊断修正**:provider 层 `OpenAICompatProvider.complete()` **已经**有 `asyncio.wait_for` + 超时捕获(handoff 原文表述不准确),设计原则"`complete()` 永远不抛异常"。真实问题是:6 个 LLM 调用点对 `LLMResult.error.kind=="timeout"` 的降级路径不一致 —— 有的 fallback 关键词、有的 skipped、有的仅日志 + 继续 —— 需统一为"timeout → skipped / 兜底"白名单。另需一个全局 safety rail(上限 60s,防 admin 配了过大 timeout)。
- **N5**:L2 测试跑在共享 dev DB 上,`pytest backend/tests/e2e/` 全量跑不动,只能跑子集。
- **N6**:`make_gbk_zip` fixture 实际产出不是它声称的"flag=0 + GBK 文件名"(Python `zipfile` 强制置位 bit 11),`fix-mac-packed-zip-parsing` 的 macOS 无 flag 修复**当前没有真正的自动化回归保障**。

4 项合起来意味着生产环境出现坏 docx / LLM 超时 / macOS 回归时,系统要么静默失败、要么长时间挂起、要么回归保障缺失。本 change 一次性把异步层的兜底、超时和测试隔离补齐。

## What Changes

- **F1 ProcessPool per-task 进程隔离(3 agent)**:`section_similarity` / `text_similarity` / `structure_similarity` 内部的 `loop.run_in_executor(get_cpu_executor(), ...)` 调用点改为 per-call `ProcessPoolExecutor(max_workers=1)` + `asyncio.wait_for(timeout=AGENT_SUBPROCESS_TIMEOUT)`。超时 / 崩溃 → agent raise **新异常 `AgentSkippedError(reason)`** → `engine._execute_agent_task` 专门捕获后走 `_mark_skipped` 路径(status="skipped",reason 写 `AgentTask.summary`)。
- **N7 LLM 调用点统一降级白名单**:6 个业务流水线调用点(`role_classifier` / `judge_llm` / `style_impl/llm_client` / `error_impl/llm_judge` / `text_sim_impl/llm_judge` / `price_rule_detector`)按职责归类降级:
  - `role_classifier` → 关键词兜底(已有,保留)
  - `judge_llm` → `risk_level=indeterminate` + `INSUFFICIENT_EVIDENCE_CONCLUSION`(honest-detection-results 已建立的证据不足路径)
  - 3 个 agent LLM 分支(style / error_consistency / text_similarity 的 llm_judge) → raise `AgentSkippedError("LLM 超时,已跳过")` 走 skipped
  - `price_rule_detector`(parser 层) → 既有兜底 + 精细化日志(parser ≠ agent,不抛 AgentSkippedError)
  - **不在 6 调用点范围**:`tester.py`(admin 连通性 API,独立降级 UI 直接回显 error.kind);`image_reuse` agent(**不调 LLM**,走 pHash + MD5 纯算法)
- **N7 全局 timeout 安全上限**:新增 `LLM_CALL_TIMEOUT`(默认 60s);`admin-llm-config` 取 timeout 时 `min(admin_timeout, LLM_CALL_TIMEOUT)` 保底。
- **N5 testdb 容器化**:新增 `docker-compose.test.yml`(独立 PostgreSQL 容器);`backend/tests/conftest.py` 按 `TEST_DATABASE_URL` 切换;`pytest backend/tests/e2e/` 全量可跑。
- **N6 `make_gbk_zip` fixture 重写**:照搬 `honest-detection-results` 已验证的"手写 ZIP 字节流"模式(本地文件头 + 中心目录 + EOCD,精确控制 flag 位)。
- **结构化副作用**:`AgentSkippedError` 新异常类(`app/services/detect/errors.py`);`AgentRunResult` **不新增字段**(reason 依旧用 `AgentTask.summary` 字符串列承载);前端**无 skip_reason 字典映射**(DimensionRow 直接渲染 summary 已是现状)。

**BREAKING**:无。所有变更对现有调用者透明,新增降级路径都落在既有 skipped 语义下。

## Capabilities

### New Capabilities
(无 — 本次全是对既有能力的鲁棒性加固)

### Modified Capabilities
- `pipeline-error-handling`: 新增"ProcessPool per-task 隔离"、"AgentSkippedError 异常契约"、"LLM 调用点降级白名单"三类 Requirement;扩展"skipped 原因文案规范"。

### 不涉及 spec 变更的部分
- **N5 testdb 容器化** / **N6 fixture 重写**:纯测试基础设施,产品行为无变化。

## Impact

- **后端代码**
  - `backend/app/services/detect/errors.py`(**新建**):`class AgentSkippedError(Exception)`
  - `backend/app/services/detect/engine.py`:`_execute_agent_task` 加 `except AgentSkippedError as exc: await _mark_skipped(session, task, str(exc))` 分支(放在通用 Exception 之前)
  - `backend/app/services/detect/agents/text_similarity.py`(line 86):包装 `run_in_executor` → per-task subprocess + timeout,crash/timeout → raise AgentSkippedError
  - `backend/app/services/detect/agents/section_sim_impl/{fallback.py:49, scorer.py:61}`:同样包装
  - `backend/app/services/detect/agents/structure_sim_impl/title_lcs.py:130`:同样包装
  - `backend/app/services/llm/factory.py`:取 admin-llm-config timeout 时 `min(admin_timeout, LLM_CALL_TIMEOUT)`
  - 6 个 LLM 调用点审计 + 统一降级(具体 diff 见 design.md)
- **配置**
  - `backend/app/core/config.py`:新增 `AGENT_SUBPROCESS_TIMEOUT`(默认 120s)、`LLM_CALL_TIMEOUT`(默认 60s)、`TEST_DATABASE_URL`
- **测试 infra**
  - `docker-compose.test.yml`(新建,顶层)
  - `backend/tests/conftest.py`(加 TEST_DATABASE_URL 切换 + module 级 TRUNCATE fixture)
  - `backend/tests/fixtures/zip_bytes.py`(**新建**):`build_zip_bytes(entries, *, flag_bits) -> bytes`
  - `backend/tests/fixtures/archive_fixtures.py`:`make_gbk_zip` 重写
  - `backend/tests/unit/test_engine_utf8_no_flag.py`:改用 `build_zip_bytes` 去重
- **前端代码**
  - **几乎无改动**。DimensionRow 已渲染 `summary`(free text),新的中文 skipped 文案直接通过 DB → API → 前端原样透出。仅需确认既有文案容器对"解析崩溃,已跳过" / "LLM 超时,已跳过" 排版 OK(task 1.1 recon 时确认,不 OK 才新增 task)
- **文档**:`docs/handoff.md` 归档时更新
- **依赖**:零新增依赖
