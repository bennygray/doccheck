## Purpose

定义 pipeline 任务(上传解析 / 检测编排)在异步路径中发生异常 / 资源问题时的
可观测性、降级语义与清理保障,保证"结果看起来 OK 实则沉默失败"的反面约束:
异常 MUST 有日志、降级 MUST 显式写入 status/summary、子进程资源 MUST 被释放。
## Requirements
### Requirement: Pipeline task 异常可观测

fire-and-forget 的 pipeline task（`asyncio.create_task`）内发生的未处理异常 SHALL 以 ERROR 级别写入日志，包含完整 traceback。

#### Scenario: try_transition_project_ready 瞬态失败
- **WHEN** `try_transition_project_ready` 因瞬态 DB 错误抛出异常
- **THEN** 异常以 ERROR 级别记录，pipeline 其余逻辑正常完成，bidder 状态不受影响

#### Scenario: pipeline task 未处理异常
- **WHEN** `run_pipeline` 抛出任何未捕获异常导致 task 终止
- **THEN** done callback 以 ERROR 级别记录异常信息和 task 名称

### Requirement: ProcessPool per-task 进程隔离

`section_similarity` / `text_similarity` / `structure_similarity` 这三个 agent 内部所有 `loop.run_in_executor(get_cpu_executor(), ...)` 调用点 SHALL 改为 per-call `ProcessPoolExecutor(max_workers=1)` + `asyncio.wait_for(timeout=AGENT_SUBPROCESS_TIMEOUT)`(默认 120s)。subprocess 崩溃(段错误 / OOM / 非零退出 / `BrokenProcessPool`)或 `asyncio.wait_for` 超时 SHALL 只影响该单份 docx 所属的那一个 agent task,其他投标人和其他维度 MUST 正常完成。

#### Scenario: 坏 docx 触发 subprocess 段错误
- **WHEN** 某投标人的 docx 在 `section_similarity` agent 的子进程内触发 python-docx/lxml 段错误,subprocess 以非零状态退出 → 该 agent raise `AgentSkippedError("解析崩溃,已跳过")`
- **THEN** 该 agent task `status=skipped`、`summary` 含"解析崩溃,已跳过";该轮其他投标人的 `section_similarity` / 其他维度(含 `text_similarity` / `structure_similarity`)正常完成并返回非 skipped 结果;`get_cpu_executor()` 共享 singleton MUST 不进入 broken 状态(per-call executor 每次用完销毁)

#### Scenario: 大文档 subprocess 超时
- **WHEN** 某投标人 docx 的 `text_similarity` 子任务运行超过 `AGENT_SUBPROCESS_TIMEOUT`
- **THEN** `asyncio.wait_for` 抛 `TimeoutError` → agent 捕获 → raise `AgentSkippedError("解析超时,已跳过")`;agent task `status=skipped`、`summary` 含"解析超时,已跳过";其他投标人 / 其他维度不受影响

#### Scenario: structure_similarity 同等保护
- **WHEN** `structure_similarity` 的 `title_lcs.py` subprocess 崩溃或超时
- **THEN** 行为对称于 `section_similarity` / `text_similarity`;该 agent task `status=skipped`、`summary` 含中文降级文案

#### Scenario: skipped 维度参与证据不足判定
- **WHEN** 某投标人的 `section_similarity` / `text_similarity` / `structure_similarity` 因 subprocess 崩溃 / 超时被标 skipped,且其他信号型 agent 全部 score=0 且无铁证
- **THEN** judge 层按 honest-detection-results 的 `SIGNAL_AGENTS` 白名单 + 证据不足规则给出 `risk_level=indeterminate` + "证据不足"结论,不产出"无围标"误导性结果

### Requirement: AgentSkippedError 异常契约

`app/services/detect/errors.py` SHALL 定义 `class AgentSkippedError(Exception)`,`__init__(self, reason: str)` 参数 reason 作为中文降级文案(已包含"已跳过"结尾)。Agent 层在遇到"应跳过"的运行期异常时 SHALL raise 此异常;`engine._execute_agent_task` SHALL 在通用 `Exception` 捕获之前专门捕获 `AgentSkippedError` 并走 `_mark_skipped(session, task, str(exc))` 路径。

**同时**:所有 agent 的 `run()` 函数内部若存在 `except Exception` 通用兜底(无论当前是否抛 AgentSkippedError),SHALL 在其**之前**前置 `except AgentSkippedError: raise`,防止 agent 未来引入 AgentSkippedError 抛出路径时,异常被通用 except 静默吞为 failed。该约束由元测试(静态扫 `agents/*.py` AST)强制。

#### Scenario: 异常被 engine 路由为 skipped
- **WHEN** 任意 agent 在 `run()` 中 raise `AgentSkippedError("LLM 超时,已跳过")`
- **THEN** engine 捕获该异常 → AgentTask `status=skipped`、`summary` 为 "LLM 超时,已跳过";不走 `_mark_failed`(status=failed) 路径

#### Scenario: 其他异常保持 failed 语义
- **WHEN** agent 在 `run()` 中 raise 非 `AgentSkippedError` 的异常(如 KeyError / ValueError)
- **THEN** engine 走既有 `_mark_failed` 路径,`status=failed`,保持与本 change 前行为一致

#### Scenario: agent 内 except 顺序防御(元测试强制)
- **WHEN** 扫 `backend/app/services/detect/agents/` 下所有 agent 入口文件的 async `run()` 函数
- **THEN** 若该函数内部的 try 块有 `except Exception` 分支,则**必须**存在一个位置严格在其之前的 `except AgentSkippedError` 分支(允许空体 `raise`,或带 OA stub 写入后 `raise`);元测试检测到缺失或顺序颠倒 SHALL 失败,防止未来新 agent 忘加或重构破坏 H2 契约

### Requirement: LLM 调用点降级白名单

所有 LLM 调用点收到 `LLMResult.error.kind == "timeout"` 或其他非 `None` error 时 SHALL 按调用点职责一致降级:
- `role_classifier` → 回落 `role_keywords.classify_by_keywords`(保留现有实现,设 `role_confidence='low'`)
- `judge_llm` → 返 `risk_level=indeterminate` + `INSUFFICIENT_EVIDENCE_CONCLUSION`,AnalysisReport 正常落库
- `style_impl/llm_client` / `error_impl/llm_judge` / `text_sim_impl/llm_judge` / `price_rule_detector` → 以 `AgentSkippedError("LLM <原因>,已跳过")` 向上抛出,由 agent run() 或 agent 入口层捕获(若 agent 自身有兜底评分则保持兜底;无兜底则 skipped)

降级分支 MUST 区分 timeout / rate_limit / auth / network / bad_response / other 六类 LLMErrorKind,写入 `AgentTask.summary` 或日志时给出具体原因码(如"LLM 超时,已跳过" vs "LLM 限流,已跳过"),便于运维诊断。

#### Scenario: agent LLM 超时走 skipped
- **WHEN** `style` / `error_consistency` / `text_similarity` 任一 agent 的 LLM 分支收到 `LLMResult(error=LLMError(kind="timeout"))` 且 agent 无本地兜底评分路径(`image_reuse` 不调 LLM,不在此范围;`tester.py` 是 admin 连通性 API 独立降级,不在此范围)
- **THEN** agent raise `AgentSkippedError("LLM 超时,已跳过")`;AgentTask `status=skipped`

#### Scenario: role_classifier LLM 失败走关键词兜底
- **WHEN** `classify_bidder` 调 LLM 收到 `LLMResult(error=...)`(任何 kind)
- **THEN** 回落 `classify_by_keywords`,文档 role 非 None(关键词命中)或 role=None(未命中),`role_confidence='low'`;解析流水线不中断

#### Scenario: judge LLM 超时 + 证据充分 → 走 fallback_conclusion(保留公式信号)
- **WHEN** `_has_sufficient_evidence` 返 True(信号充分),随后 `judge_llm._call_llm_judge` 收到 `LLMResult(error=LLMError(kind="timeout"))`
- **THEN** judge 走既有 `fallback_conclusion(final_total, formula_level, ...)` 路径,返结论前缀 `AI 综合研判暂不可用,以下为规则公式结论:...`;`risk_level` = formula_level(high/medium/low,**不**强行降 indeterminate — 证据 IS 充分,只是 LLM 建议拿不到);AnalysisReport 正常落库,`report_ready=true`

#### Scenario: judge 证据不足 → 走 INSUFFICIENT_EVIDENCE_CONCLUSION
- **WHEN** `_has_sufficient_evidence` 返 False(honest-detection-results 白名单 + 铁证短路后判定真的证据不足)
- **THEN** judge **不**调 LLM,直接返 `risk_level=indeterminate` + `INSUFFICIENT_EVIDENCE_CONCLUSION`;AnalysisReport 正常落库,`report_ready=true`

#### Scenario: LLM 限流写具体原因码
- **WHEN** 任一调用点收到 `LLMError(kind="rate_limit")`
- **THEN** `AgentTask.summary` 或日志区分"LLM 限流,已跳过"(而非含糊的"LLM 错误")

### Requirement: LLM 调用全局 timeout 安全上限

`backend/app/core/config.py` SHALL 暴露两个独立 timeout 字段:

- `LLM_TIMEOUT_S` → `Settings.llm_timeout_s`(per-call 实际超时,默认 **300 秒**)
- `LLM_CALL_TIMEOUT` → `Settings.llm_call_timeout`(全局 cap,默认 **300 秒**)

`app/services/llm/factory.py` 在构造 `OpenAICompatProvider` 时 SHALL 通过 `_cap_timeout(raw)` 取 `min(raw, llm_call_timeout)` 作为有效 timeout,其中 `raw` 来自 env 路径的 `settings.llm_timeout_s` 或 admin-llm-config DB 路径的 `cfg.timeout_s`。两者并联语义:任一压低 → 实际生效压低;cap 仅当 per-call 配置过大时兜底,不会反向把 per-call 拉高。

默认值同步到 300 的原因(承接 `2026-04-24-config-llm-timeout-default`):前一次 change 只改了 cap 默认值 60→300,但 per-call(`llm_timeout_s`)默认仍是 30,实际生效 = `min(30, 300) = 30`,慢模型(ark-code-latest 类,role_classifier 实测 35~132s,price_rule_detector 实测 ~113s)仍高概率超时。本次把 per-call 默认也对齐到 300,`min(300, 300) = 300`,真正给慢模型留够空间。

部署文件(`backend/.env.example`、`docker-compose.yml`)SHALL 与代码默认值保持同步:`docker-compose.yml::LLM_TIMEOUT_S` 默认值 = `${LLM_TIMEOUT_S:-300}`;`.env.example` 注释 SHALL 显式说明 per-call 与 cap 的并联关系,避免用户误以为只配 cap 即可。

#### Scenario: admin 配置过大 timeout 被 cap

- **WHEN** admin-llm-config 存储的 timeout=1200(秒),LLM_CALL_TIMEOUT=300
- **THEN** 实际 provider 的 `_timeout_s` 取 300(非 1200);provider 层 asyncio.wait_for 仍按 300 生效

#### Scenario: admin 配置小 timeout 保持不变

- **WHEN** admin-llm-config 存储的 timeout=15,LLM_CALL_TIMEOUT=300
- **THEN** 实际 provider 的 `_timeout_s` 取 15

#### Scenario: LLM_CALL_TIMEOUT 可通过 env 覆盖

- **WHEN** 部署环境 `export LLM_CALL_TIMEOUT=60`
- **THEN** `config.llm_call_timeout = 60`,factory 层取 `min(per_call, 60)`

#### Scenario: 未配 env 时 per-call 与 cap 默认值都是 300

- **WHEN** 未设置 `LLM_TIMEOUT_S` 或 `LLM_CALL_TIMEOUT` 环境变量,且 admin-llm-config 未存 timeout
- **THEN** `config.llm_timeout_s = 300.0` 且 `config.llm_call_timeout = 300.0`(均为 code 默认);factory 层 `_cap_timeout(300)` = `min(300, 300)` = 300,provider 层按 300s 生效;ark-code-latest 单次最坏 132s LLM 调用不再超时

#### Scenario: per-call env 压低生效

- **WHEN** 部署环境 `export LLM_TIMEOUT_S=60`,无 LLM_CALL_TIMEOUT env(cap 取代码默认 300)
- **THEN** `config.llm_timeout_s = 60`,factory 层取 `_cap_timeout(60)` = `min(60, 300) = 60`;provider 层按 60s 生效;想要快速失败的部署可主动压低 per-call 而不动 cap

### Requirement: Windows 控制台日志 UTF-8 兜底

`backend/app/main.py` lifespan 在启动初段(tracker 注册前)SHALL 尝试对 `sys.stdout` / `sys.stderr` 执行 `reconfigure(encoding="utf-8", errors="replace")`;AttributeError / ValueError 场景下静默跳过(test client / 容器化部署等 stream 已被替换的场景不报错)。

此契约防御 Windows 默认 GBK 控制台对含 `U+00BA` 等冷门 Unicode 字符的中文日志触发 `UnicodeEncodeError` 导致 logging emit 崩溃(2026-04-24 E2E 验证实测)。

#### Scenario: Windows GBK 控制台启动
- **WHEN** `uvicorn` 在 Windows 默认 cmd / PowerShell(GBK 编码)启动
- **THEN** lifespan 顶部成功 reconfigure stdout/stderr 为 utf-8;后续 logger 输出含 `U+00BA` 等罕见字符不再 crash

#### Scenario: stdout 已被测试框架替换
- **WHEN** pytest 的 capsys / caplog 已把 sys.stdout 替换为 StringIO 或 CaptureIO
- **THEN** `sys.stdout.reconfigure` 调用触发 AttributeError(StringIO 无 reconfigure),try/except 兜底吞异常,lifespan 继续启动不中断

### Requirement: skipped 原因文案规范

`AgentTask.summary` 在 skipped 状态下 SHALL 使用中文短文案,格式 `"<具体原因>,已跳过"`,长度 ≤50 字。具体原因包括但不限于:
- "解析崩溃" / "解析超时"(子进程层)
- "LLM 超时" / "LLM 限流" / "LLM 鉴权失败" / "LLM 网络错误" / "LLM 返回异常"
- 既有 preflight skip reason(无目标文档 / 证据不足等)保留

前端 / Word 导出层 SHALL 原样透传该文案,不做额外字典映射。

#### Scenario: 前端原样展示 summary
- **WHEN** 某 agent task `status=skipped`, `summary="解析崩溃,已跳过"`,后端 `/analysis/status` 返该字段
- **THEN** 前端 DimensionRow 原样渲染 "解析崩溃,已跳过",不新增 skip_reason 字段或字典映射

#### Scenario: Word 导出保留 summary
- **WHEN** `/reports/{id}/export-word` 生成 Word 文档包含该 skipped agent 的段落
- **THEN** Word 段落文本包含 `summary` 字符串,不翻译 / 不改写

### Requirement: 测试基础设施鲁棒性契约

为防止"前序 hardening 的契约在基础设施噪声中被静默破坏",本 capability SHALL 锁定以下 3 个稳定测试基础设施契约点(不锁 heuristic / 参数阈值 / 内部实现,只锁可观测行为):

- **alembic migration 不 disable 应用 logger**:`backend/alembic/env.py` 调用 `logging.config.fileConfig(...)` 时 MUST 显式传 `disable_existing_loggers=False`,保证任何 `app.*` logger 在 alembic upgrade head 跑完后仍可用(`.disabled is False`)。防止 L2 session fixture 意外屏蔽应用 logger 导致 caplog 类测试静默失败
- **`run_isolated` 对 `ProcessPoolExecutor` 内部字段变动 graceful degrade**:finally 块访问 `pool._processes` MUST 通过 `getattr(pool, "_processes", {})` + `try/except (AttributeError, TypeError)` 双重守卫;缺失或非预期类型时 fallback 到纯 `shutdown(wait=False, cancel_futures=True)` 路径,不 raise 到调用方。保证 Py 3.14+ stdlib 潜在变动下 `run_isolated` 仍可被调用且不破坏 isolate 语义
- **engine 层 except 顺序契约由 AST 元测试强制**:`engine._execute_agent_task` 的 `except AgentSkippedError` 必须严格位于 `except Exception` 之前,由 L1 AST 元测试(非正则/文本扫描)静态校验 —— 元测试 MUST 用 `ast.AsyncFunctionDef` visitor 遍历 try 块 handler,确定顺序索引,禁止正则去注释类脆弱方案

本 Requirement 不引入新产品行为,不改 schema / API / 前端;只把 3 个**已在 harden-async-infra / agent-skipped-error-guard / llm-classifier-observability 隐含建立**的契约显式化,防未来回归。

#### Scenario: alembic upgrade 不 disable app logger

- **WHEN** L2 session fixture `_testdb_schema` 启动时调 `alembic upgrade head`,触发 `alembic/env.py:27` 的 `fileConfig(config.config_file_name, disable_existing_loggers=False)`
- **THEN** 此前已通过 `logging.getLogger("app.services.parser.content")` 等 API 创建的应用层 logger 在命令返回后 `.disabled is False`;后续 `caplog.at_level(logging.WARNING, logger="app.services.parser.content")` + `logger.warning(...)` 可被 caplog 捕获

#### Scenario: run_isolated 对 pool 内部字段缺失 graceful fallback

- **WHEN** `run_isolated` 的 `ProcessPoolExecutor` 实例 `_processes` 属性缺失、类型变化、或访问 raise AttributeError/TypeError
- **THEN** finally 块 catch 异常 fallback 到 `processes = []`;继续执行 `pool.shutdown(wait=False, cancel_futures=True)` 完成最基本的资源释放;不 raise 到调用方,agent 任务按既有语义返回 result 或标 skipped/timeout

#### Scenario: engine except 顺序由 AST 元测试校验

- **WHEN** 扫 `backend/app/services/detect/engine.py::_execute_agent_task` 函数定义,解析为 `ast.AsyncFunctionDef`,遍历其 `body` 内所有 `ast.Try` 节点
- **THEN** 若某 try 块的 `handlers` 含 `ast.ExceptHandler(type=ast.Name(id="Exception"))`(通用兜底),则**必须**存在一个位置索引严格小于该 handler 的 `ast.ExceptHandler(type=ast.Name(id="AgentSkippedError"))`;顺序颠倒或缺失 SHALL 令元测试失败,定位到具体文件行号

### Requirement: 前端交互测试 timing 契约

前端 `userEvent`-based 交互测试(vitest + React Testing Library + `@testing-library/user-event`)在全量 `npm test -- --run` 跑下 SHALL 稳定通过,不因 vitest worker / jsdom / AST transform 资源累积导致默认 5000ms 超时。为此,涉及多次 `user.click` / `user.type` 的 async 测试 SHALL 满足以下二选一:

- **首选**:`userEvent.setup({ delay: null })`(移除 keystroke 间 microtask tick,userEvent v14 推荐方式),不改测试语义只改 timing
- **兜底**:若该测试场景需要模拟真实用户打字节奏(极少数 UX 依赖 debounce 的边缘 case),SHALL 显式提供 test-level timeout ≥15000ms(`test("...", async () => {...}, 15000)`),明确承认全量跑的资源压力

全新引入的前端交互测试(`userEvent.setup()` 调用)MUST 遵循本契约,防未来 suite 膨胀再次触发 5s 超时 flaky。

#### Scenario: AdminUsersPage 创建用户测试在全量跑下稳定绿

- **WHEN** `frontend/src/pages/admin/AdminUsersPage.test.tsx::创建用户成功` 测试的 `userEvent.setup()` 调用传入 `{ delay: null }` 参数
- **THEN** `cd frontend && npm test -- --run` 在至少连续 3 次全量跑下,该测试 pass;同时 `npm test -- --run AdminUsersPage` 隔离跑也 pass;两种模式行为一致,不再出现 `Test timed out in 5000ms` 报错

