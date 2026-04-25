## MODIFIED Requirements

### Requirement: ProcessPool per-task 进程隔离

`section_similarity` / `text_similarity` / `structure_similarity` 这三个 agent 内部所有 `loop.run_in_executor(get_cpu_executor(), ...)` 调用点 SHALL 改为 per-call `ProcessPoolExecutor(max_workers=1)` + `asyncio.wait_for(timeout=AGENT_SUBPROCESS_TIMEOUT)`(默认 120s)。subprocess 崩溃(段错误 / OOM / 非零退出 / `BrokenProcessPool`)或 `asyncio.wait_for` 超时 SHALL 只影响该单份 docx 所属的那一个 agent task,其他投标人和其他维度 MUST 正常完成。

`section_similarity` agent 内部对 N 个章节对的 TF-IDF 计算 SHALL 在**单一** `run_isolated` 调用内批量完成(子进程内串行循环 N 次纯计算),禁止 per-pair 调用 `run_isolated`。理由:Windows / Python 3.13 实测 per-pair spawn 路径下,每次新子进程的 jieba 词典冷启动(~600ms)+ ProcessPoolExecutor spawn(~230ms)+ numpy/sklearn import + IPC 序列化合计 ~3s 固定开销,N×3s 在 N>50 章节对时撞 300s `AGENT_TIMEOUT_S`(2026-04-26 e2e 实测三对 pairwise 全 timeout,elapsed_ms 卡 300149/302205/301276)。批量化后固定开销从 O(N) 降到 O(1),N=300 章节对单 spawn 内总耗时 ~70s,远低于 120s `agent_subprocess_timeout`。

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

#### Scenario: section_similarity 章节对计算批量化
- **WHEN** `section_sim_impl/scorer.py::score_all_chapter_pairs` 处理 N 个 `chapter_pairs`(N>=1)
- **THEN** 整个 scorer 函数内 `run_isolated` 的调用次数 MUST = 1(用 monkeypatch 计数的 L1 元测试静态校验);N 个章节对的 TF-IDF 计算在该单次 spawn 出的子进程内串行执行,jieba 词典只加载一次

#### Scenario: section_similarity 批量子进程超时走 skipped
- **WHEN** `section_sim_impl/scorer.py` 的批量 `run_isolated` 调用因 N 极大或 docx 异常导致子进程内总耗时 > `agent_subprocess_timeout`(默认 120s)
- **THEN** `run_isolated` 抛 `AgentSkippedError(SUBPROC_TIMEOUT)`;agent run() 不再走章节级 → 整文档级 fallback(批量崩信号意义不同),由 engine `_mark_skipped` 标 task `status=skipped`、`summary` 为"解析超时,已跳过";其他维度不受影响
