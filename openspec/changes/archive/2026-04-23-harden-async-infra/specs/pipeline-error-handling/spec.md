## ADDED Requirements

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

#### Scenario: 异常被 engine 路由为 skipped
- **WHEN** 任意 agent 在 `run()` 中 raise `AgentSkippedError("LLM 超时,已跳过")`
- **THEN** engine 捕获该异常 → AgentTask `status=skipped`、`summary` 为 "LLM 超时,已跳过";不走 `_mark_failed`(status=failed) 路径

#### Scenario: 其他异常保持 failed 语义
- **WHEN** agent 在 `run()` 中 raise 非 `AgentSkippedError` 的异常(如 KeyError / ValueError)
- **THEN** engine 走既有 `_mark_failed` 路径,`status=failed`,保持与本 change 前行为一致

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

`backend/app/core/config.py` SHALL 暴露 `LLM_CALL_TIMEOUT`(默认 60 秒);`app/services/llm/factory.py` 从 admin-llm-config 读 timeout 时 SHALL 取 `min(admin_timeout, LLM_CALL_TIMEOUT)` 作为有效 timeout,传给 `OpenAICompatProvider`。admin 层 UI 无需改动,该上限仅在 factory 层防御。

#### Scenario: admin 配置过大 timeout 被 cap
- **WHEN** admin-llm-config 存储的 timeout=600(秒),LLM_CALL_TIMEOUT=60
- **THEN** 实际 provider 的 `_timeout_s` 取 60(非 600);provider 层 asyncio.wait_for 仍按 60 生效

#### Scenario: admin 配置小 timeout 保持不变
- **WHEN** admin-llm-config 存储的 timeout=15,LLM_CALL_TIMEOUT=60
- **THEN** 实际 provider 的 `_timeout_s` 取 15

#### Scenario: LLM_CALL_TIMEOUT 可通过 env 覆盖
- **WHEN** 部署环境 `export LLM_CALL_TIMEOUT=30`
- **THEN** `config.LLM_CALL_TIMEOUT = 30`,factory 层取 `min(admin_timeout, 30)`

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
