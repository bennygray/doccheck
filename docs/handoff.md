# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M4 完成 + V1 全量验收 + admin-llm-config + fix-mac-packed-zip-parsing + honest-detection-results + harden-async-infra + agent-skipped-error-guard + llm-classifier-observability(N3 收官)+ test-infra-followup-wave2(前序 hardening 5 项 follow-up 清理) + fix-admin-users-page-flaky-test(前端 flaky 收官)** |
| 当前 change | `fix-admin-users-page-flaky-test` 归档完成。`test-infra-followup-wave2` 遗留的前端 AdminUsersPage `创建用户成功` 全量跑 flaky(`Test timed out in 5000ms`)。**apply 期发现 design D1/D2 先后预估错**:单独 `userEvent.setup({ delay: null })` 3/3 稳定 fail(不是 design 预估的 <5% 偶发);必须同时加 test-level `timeout=15000ms`(D2 fallback)才稳定。最终主备同出:`AdminUsersPage.test.tsx` L100 `userEvent.setup({ delay: null })` + L81 test 第 3 参数 15000;`openspec/specs/pipeline-error-handling/spec.md` +1 Requirement "前端交互测试 timing 契约"(首选 delay:null,兜底 test-level timeout≥15s)。前端 L1 **114/114 绿连续 3 次稳定**(45s×3 轮);scope 锁死只改 1 站点(其他 14+ `userEvent.setup()` 无病例不动,spec 约束未来新测试);零产品行为变化 |
| 先前 change | `test-infra-followup-wave2` 归档完成。5 项测试/诊断基础设施 follow-up 合 1 change:**Item 1(🔴 real bug)** `alembic/env.py:27` 加 `disable_existing_loggers=False` 参数,根治 L2 session fixture `alembic upgrade head` 静默 disable 所有 `app.*` logger 的副作用;**test_xlsx_truncates_oversized_sheet FAIL→PASS,L2 从 280+1fail 变 281/281 全绿**;**Item 2(🟡 latent)** `test_engine_agent_skipped_error.py` engine except 顺序断言从正则去注释升级 AST visitor(复用 agent-skipped-error-guard pattern),AST 级意外发现老正则漏掉的 preflight try(非 bug 但契约精修:仅 body 调 `_mark_failed` 的 broad except 强制 AgentSkippedError 前置);**Item 3(🟡 latent)** `run_isolated` finally `_processes` 访问加 `try: ... except (AttributeError, TypeError)` future-proof Py 3.14+,静态源码断言 3 case + 实跑 happy path 1 case(mock 路径破坏 pool 本体已在 apply 期推翻);**Item 4(🟡 诊断盲区)** `main.py` lifespan 顶部 `logging.getLogger("app").setLevel(logging.INFO)` + try/except 兜底,让 uvicorn `--log-level info` 级联 app logger 子树,解决 llm-classifier-observability 暴露的诊断盲区;**Item 6(🟢 覆盖空白)** DimensionRow 追加 2 case 覆盖 text_sim degraded 非 skipped 真实 shape(`succeeded:1 + best_score=42.5 + _DEGRADED_SUMMARY`);`openspec/specs/pipeline-error-handling/spec.md` +1 ADDED Requirement 锁 3 稳定契约点。L1 1020/1020 + 5 skipped;L2 **281/281 绿**;前端 113/114(1 pre-existing AdminUsersPage flaky 与本 change 无关,下个 change 处理);零产品行为变化 |
| 先前 change | `llm-classifier-observability` 归档完成。N3 LLM 大文档精度退化 explore 后的观测性 change:`role_classifier.py` 3 条 info 日志补齐 3 决策路径的诊断信号(input shape / output confidence mix / invalid JSON raw_text_head)+ `_looks_mojibake` heuristic 识别 cp850→GBK 乱码文件名 + 1 ADDED Requirement 进 parser-pipeline spec 固化契约;双采样脚本 `e2e/artifacts/supplier-ab-n3-observability/run_sampling.py` B 方案跑了真 LLM(ark provider)2 轮,**证明 N3 原始症状不再复现**(A/B 均 high=3 low=0,跨轮完全一致),根因 H2a(`._` AppleDouble 污染 prompt)已被 `fix-mac-packed-zip-parsing` 消除。观测性代码作为未来回归武器存档。2 个就地发现:(a) uvicorn `--log-level info` 不级联 app logger,本次靠 DB + warning 缺席推导;(b) 脚本 `file_role` 字段取错已就地修复。L1 1011/1011 + L2 280 passed/1 pre-existing fail,零回归。|
| 先前 change | `harden-async-infra` 归档完成。基础设施鲁棒性 4 项合并修复:**F1 ProcessPool per-task 隔离** — 3 个 CPU agent(section/text/structure_similarity)的共享 `get_cpu_executor()` 调用点改为 per-call `ProcessPoolExecutor(max_workers=1)` + `asyncio.wait_for(AGENT_SUBPROCESS_TIMEOUT=120s)` + finally `terminate()/kill()` 主动清理(防 hang worker zombie);新 `AgentSkippedError` 异常作为 agent→engine 的 skipped 信号通道,engine `_execute_agent_task` 在 `except Exception` 之前专捕获走 `_mark_skipped` 路径。**N7 LLM 降级归一 + 全局 cap** — 6 LLM 调用点按职责归一:style(无本地兜底)→ `_call_with_retry_and_parse` 重试耗尽 raise AgentSkippedError + OA stub 写入(reviewer H2 保持 UI 维度条目完整)+ style.py `except AgentSkippedError: raise`;error_consistency / text_similarity 有本地兜底保留 + 精细化 kind 日志;judge_llm 三路径对齐(_has_sufficient_evidence==False→indeterminate;True+LLM ok→clamp;True+LLM fail→fallback_conclusion 保留公式信号);role_classifier / price_rule_detector 保留原降级 + kind 日志;新 `factory._cap_timeout` helper 两路径(env `get_llm_provider()` / DB `get_llm_provider_db()`)统一 cap 到 `settings.llm_call_timeout=60s` + None/0/负数防御 + cache key `max(1, int(...))` 防 0<raw<1 塌陷。**N5 testdb 容器化** — `docker-compose.test.yml`(postgres:16-alpine,port 55432,volume 匿名);`backend/tests/conftest.py` 顶层 sys.argv e2e 粗判 + `tests/e2e/conftest.py::_testdb_schema` session fixture loud-fail(双层防御)+ alembic upgrade head 程序化;未设 TEST_DATABASE_URL 跑 e2e → pytest.exit(code=2) 引导文案,不静默退回 dev DB。**N6 make_gbk_zip fixture 重写** — 抽 `tests/fixtures/zip_bytes.py::build_zip_bytes(entries, *, flag_bits)` helper(手写 LFH/CDE/EOCD 精控 flag_bits);`make_gbk_zip` flag=0 GBK 字节真实产出(old 版 stdlib `zipfile` 强制置位 bit 11 导致 fix-mac-packed-zip-parsing 的自动回归失效);`test_engine_utf8_no_flag.py` 内部 helper 走 thin shim 去重。**集中 skip reason 常量** — `backend/app/services/detect/errors.py` 7 条文案常量(`SKIP_REASON_SUBPROC_CRASH`/`_SUBPROC_TIMEOUT`/`_LLM_TIMEOUT`/`_LLM_RATE_LIMIT`/`_LLM_AUTH`/`_LLM_NETWORK`/`_LLM_BAD_RESPONSE`)+ `llm_error_to_skip_reason(kind)` helper,防站点字符串漂移 |
| 最新 commit | harden-async-infra 归档 |
| 工作区 | **后端代码**:新建 `services/detect/errors.py`(AgentSkippedError + 7 常量 + helper)+ `services/detect/agents/_subprocess.py`(run_isolated)+ `docker-compose.test.yml`(顶层);改 `core/config.py`(+agent_subprocess_timeout / llm_call_timeout);`services/detect/engine.py::_execute_agent_task`(+ AgentSkippedError 分支 + 导入);`services/detect/agents/{text_similarity, section_sim_impl/{fallback, scorer}, structure_sim_impl/title_lcs}.py`(run_in_executor → run_isolated);`services/detect/agents/style_impl/llm_client.py`(_call_with_retry_and_parse 抛 AgentSkippedError)+ `agents/style.py`(except AgentSkippedError 写 OA stub + re-raise);`services/detect/agents/error_consistency.py`(预防性 except AgentSkippedError);`services/detect/agents/error_impl/llm_judge.py`(last_kind 日志);`services/detect/agents/text_sim_impl/llm_judge.py`(注释归一);`services/parser/llm/{role_classifier, price_rule_detector}.py`(日志带 kind+msg);`services/llm/factory.py`(_cap_timeout helper + 两路径 cap + cache key max(1, int()));**测试 infra**:新建 `tests/fixtures/zip_bytes.py`(build_zip_bytes)、改写 `tests/fixtures/archive_fixtures.py::make_gbk_zip`;`tests/conftest.py`(顶层 TEST_DATABASE_URL 覆盖);`tests/e2e/conftest.py`(session schema fixture + testdb_clean module fixture);`backend/README.md`(L2 测试如何跑 3 行);**测试**:L1 新增 `test_skip_reason_constants.py`(17)/`test_agent_subprocess_isolation.py`(6,含 hang 回归 + 平台感知 zombie 阈值)/`test_engine_agent_skipped_error.py`(2,源码级顺序)/`test_llm_timeout_cap.py`(11,两路径 + 防御三份)/`test_llm_call_site_downgrade.py`(8,matrix)/`test_fixture_gbk_zip.py`(3,对称参数化 flag=0/0x800)+ 扩展 `test_judge_insufficient_evidence.py`(+1 reviewer M3 skipped filter)+ 改写 `test_style_llm_client.py`(3 case 从 return None → raise);L2 新增 `test_detect_subprocess_isolation.py`(4,AgentSkippedError 端到端 + SIGNAL_AGENTS 全 skipped → indeterminate)/`test_llm_timeout_pipeline.py`(2,style skipped + report_ready=true)+ 改 `test_judge_llm_e2e.py`(加 _seed_agent_tasks_succeeded 满足 _has_sufficient_evidence,clean testdb 暴露老测试隐含依赖);前端 `DimensionRow.test.tsx` +8 参数化(7 skip 文案 + 1 text_sim degraded);**L1 988/988 绿;L2 274/275 绿**(1 deselect = pre-existing `test_xlsx_truncates_oversized_sheet` caplog 问题与本 change 无关);**合并 1268/1269 in 3:17**;**manual 凭证**:`e2e/artifacts/harden-async-infra-2026-04-23/README.md` 指向 L2 自动化测试套 6 case 真 DB+API 集成验证作凭证;**spec sync**:`pipeline-error-handling` 加 5 Req(ProcessPool 隔离 / AgentSkippedError 契约 / LLM 降级白名单 / LLM_CALL_TIMEOUT 上限 / skipped 文案规范)+ 12 scenario(3.6 在 apply 中修正对齐代码:judge LLM 超时 + 证据充分 → fallback_conclusion 保留公式信号,不强降 indeterminate) |

---

## 2. 本次 session 关键决策(2026-04-23,`fix-admin-users-page-flaky-test` propose+apply+archive)

### 上游触发
`test-infra-followup-wave2` 归档时遗留:前端全量跑 `npm test -- --run` 1 个 pre-existing flaky `AdminUsersPage 创建用户成功`(clean tree 同失败,isolated 跑绿),用户要求下一个 change 处理。

### propose 1 个产品决策(Q1=B 加 minimal spec)
- 小 fix 也走 openspec flow(CLAUDE.md 惯例);spec 加 1 ADDED Requirement "前端交互测试 timing 契约" 锁未来契约,不只修 bug

### apply 现场决策(技术层,不问用户)
- **D1 推翻**:design 预估 `userEvent.setup({ delay: null })` 单独足够,实测 3/3 稳定 fail(不是偶发!)—— 全量跑下 jsdom + antd + vitest workers 累积负载远比 keystroke delay 严重
- **D2 实测触发**:design 预估 fallback "<5% 偶发" 才加 timeout=15000,apply 期直接触发(100% 需要兜底);主备同出才稳定
- **spec 描述修正对齐实测**:从 "首选 delay:null,兜底 timeout" 改写为 "delay:null 或 test-level timeout≥15s 二选一或组合",契约意图保留但表述更精确(非更严格)
- **scope 锁死**:全项目 15+ `userEvent.setup()` 站点只改出问题的那 1 个(L100),其他 14 个无病例不动;spec 约束**未来**新测试,不追溯批改历史(memory 无病例不 preemptive 修复)

### 文档联动
- **`openspec/specs/pipeline-error-handling/spec.md`** +1 Requirement "前端交互测试 timing 契约" + 1 scenario
- **`docs/handoff.md`** 即本次更新

### 关键收益
- 前端 L1 **114/114 全绿连续 3 次稳定**(vs 前 113/114 稳定 fail)
- 未来前端 change 归档前 "npm test 全绿" 校验门从"1 fail 人工 pass" 回归到 "全绿自动 pass"
- spec 契约防未来新测试引入同型 flaky

### 遗留到下次 / backlog
- **Follow-up(低优)**:项目其他 14 个 `userEvent.setup()` 站点(AddBidderDialog / PriceConfigForm / PriceRulesPanel / AdminLLMPage / AdminRulesPage / ProjectCreatePage / AdminUsersPage 自身 L126)目前全绿无症状,无病例不主动修;若未来 suite 继续膨胀触发同型 flaky,单独处理
- **Follow-up(低优,pre-existing)**:9 个 spec validate 失败(handoff L58,scope 大,逐个看)

---

## 2.bak_test-infra-followup-wave2 上一 session 关键决策(2026-04-23,`test-infra-followup-wave2` propose+apply+archive)

### 上游触发
用户汇总前 3 次 change(harden-async-infra / agent-skipped-error-guard / llm-classifier-observability)的 3 条遗留(1 real bug + 2 latent),要求合 1 处理。handoff 扫出另 2 项同主题的 follow-up(uvicorn log 不级联 / text_sim degraded 前端覆盖空白),拒 1 项 scope 大的(9 个 spec validate 失败)、拒 1 项不同域的(前端 vitest flaky),最终 5 项 + handoff stale 清理合 1 change。

### propose 1 个产品决策(A/B/C bundle,对齐 A 合 1)+ 1 个新纳决策(Item 4 也纳入)
- 范围由 3 → 5 + 清理,scope 从 "合并前序 reviewer 遗留" 扩到 "合并前序 reviewer 遗留 + 本周发现的同主题 follow-up"
- Item 1 在 llm-classifier-observability apply 期 recon 已完全锁定根因(alembic fileConfig disable_existing_loggers=True),propose 阶段无遗留模糊;其他 4 项 design 级自决

### apply 现场决策(技术层,不问用户)
- **D1 Item 1**:alembic env.py 加 1 keyword arg(disable_existing_loggers=False),对 prod 严格更宽松
- **D2 Item 2 AST 级意外发现**:apply 期初版 AST 断言比老正则更严,flag 到 preflight try(broad except body 调 `_mark_skipped`,非 bug);精修契约为"仅 body 调 `_mark_failed` 的 broad except 强制 AgentSkippedError 前置",AST 真契约反而更准
- **D3 Item 3 mock 路径推翻**:apply 期实测 mock `_processes` 缺失直接破坏 pool 本体(stdlib `_adjust_process_count` 本身用 `_processes`),mock 拖垮 pool 启动而不是测 finally 块;切静态源码断言(try/except 结构 / fallback workers=[] / shutdown 调用)+ 实跑 happy path,更第一性、更稳
- **D4 Item 4 只 setLevel**:不搞 dictConfig / yaml,1 行 setLevel 让 `app.*` 子树默认 INFO;handler 级由 uvicorn/env 控制,prod warning 级不误爆 info
- **D5 Item 6 apply 期发现 DimensionRow 不消费 evidence_json**:frontend 层 DimensionRow 只读 `summaries[0]`,evidence_json 在 evidenceSummary 工具里消费;修正 Item 6 的测试语义为"degraded 非 skipped 的真实 shape(succeeded=1 + best_score>0)渲染回归网",贴近真实用户路径
- **pool._processes 反向验证案例**:apply 期跑 test_run_isolated_future_proof 3 次 mock 路径全 fail `'ProcessPoolExecutor' object has no attribute '_processes'`(stdlib 运行期自己需要),推翻 design 的 mock 方案;改静态断言 + happy path,同文件 4/4 绿

### 文档联动
- **`openspec/specs/pipeline-error-handling/spec.md`** 加 1 Requirement "测试基础设施鲁棒性契约" + 3 scenarios(alembic 不 disable app logger / `run_isolated` graceful degrade / engine except 顺序 AST 元测试)
- **`docs/handoff.md`** 即本次更新 + §2.bak_honest-detection-results 里 2 条 stale 项 strikethrough(agent 全仓 except guard 已被 agent-skipped-error-guard 落地 / text_sim _DEGRADED_SUMMARY 已被本 change Item 6 补强)
- **`backend/app/main.py`** lifespan 顶部 setLevel 注释引本 change

### 关键收益
- **L2 从 280/1fail 变 281/281 全绿**:Item 1 fix 顺带治好 pre-existing 稳定失败的 `test_xlsx_truncates_oversized_sheet`
- **engine except 顺序 AST 契约**:防未来重构破坏 harden-async-infra D2 核心(AgentSkippedError 必须在 Exception 之前),且精确到 `_mark_failed` 触发条件,不误报 preflight skipped 路径
- **run_isolated Py 3.14+ 兼容网**:stdlib 移除 `_processes` 时 graceful degrade,fallback 到纯 shutdown 路径
- **uvicorn log 级联修复**:未来 N3 类诊断 info 日志天然可见,不用再改 main.py
- **DimensionRow 前端降级文案回归网**:防未来改 DimensionRow 把 text_sim succeeded + summaries[0] 吞掉

### 遗留到下次 / backlog
- **Follow-up(下一个 change)**:`frontend/src/pages/admin/AdminUsersPage.test.tsx::创建用户成功` 全量跑 flaky(clean tree 上同失败,隔离跑绿,与本 change 无关)。用户已明确要求下一个 change 处理
- **Follow-up(低优,pre-existing)**:9 个 spec validate 失败(handoff L58,scope 大,逐个看),可后续单开

---

## 2.bak_llm-classifier-observability 上一 session 关键决策(2026-04-23,`llm-classifier-observability` explore+propose+apply+archive)

### 上游触发
`harden-async-infra` + `agent-skipped-error-guard` 归档后,唯一的 N3 backlog(LLM 大文档精度退化)进入 `/openspec-explore`。explore 阶段发现 harden-async-infra 补的 kind 日志只覆盖 3 决策路径中的 1 条(provider error),另 2 条(LLM 成功但自返 low / JSON 解析失败)完全隐身。无采样前任何 hardening 都是盲修。

### explore 阶段发现
- role_classifier 现有决策有 3 分支:`result.error != None`(有 kind 日志)/ `_parse_llm_json == None`(有 invalid JSON 日志但无 raw head)/ `LLM 成功返 low`(无日志);前 2 条可见,第 3 条需新加 info 日志
- 用户选 B 双采样(A+B × 2 轮,约 ¥0.2)以观察稳定性

### propose 2 个产品决策(Q1 对齐)
- **Q1 A**:最小 spec 改动。openspec validate 强制至少 1 delta,不能零 spec;折衷方案是写最小 ADDED Requirement(1 Req + 3 scenarios),只锁定"3 个日志点的存在性",不写 heuristic 细节 / 字段阈值等可变项
- 未来若 N3 数据指向 hardening 方向,在**下一个 change** 里再改 spec,本 change scope 锁死观测性

### apply 现场决策(技术层,不问用户)
- **D1 log level = info**:3 条新增日志用 logger.info(prod 默认 warning 级不显示,零噪声;诊断时主动调低)。既有 kind / invalid JSON warning 保留 warning 级不变
- **D2 只改 role_classifier 一个站点**:N3 只在 role_classifier 观察到;其他 5 LLM 调用点已有 kind 日志,不扩 scope
- **D3 mojibake heuristic**:纯启发式零依赖(25 个 cp850→GBK 乱码片段 markers,`any(m in name for m in markers)`),诊断用不触发业务控制流,误判无成本
- **D4 raw_text head 200 字符**:扩展既有 invalid JSON warning,追加 `raw_text_head=%r`,按字符(code point)截取 Unicode 安全
- **D5 采样脚本不复用 `run_detection.py`**:那是 detect 流水线,本 change 要的是 parse 流水线 + per-bidder snapshot,概念不同;强行抽 shared lib 反而 scope 爆炸
- **L1 fixture 复刻既有 `test_role_classifier_content_fallback.py` 风格**:独立 prefix `rc_obs_` 保证清理域不重叠(memory 习惯),不抽 shared lib

### Task 3.3 端到端 manual 执行(2026-04-23 session 内由 Claude 代跑)
- 起 dev postgres + alembic upgrade head + uvicorn(ark provider env 回退 admin-llm)
- `run_sampling.py` 2 轮 A+B,真 LLM(ark-code-latest),耗时约 2 分钟
- 产出 `round1.json` / `round2.json` / `comparison.json` / `backend.log`(311K)/ `sampling_run.log`
- **N3 原始症状不复现**:2 轮均 A/B `role_confidence_mix={high:3,low:0,none:0}`,完全一致
- 根因追溯:原 N3 是 H2a(`._` AppleDouble 文件污染 prompt,LLM 对混杂 8-10 条目的 prompt 整体降信心),`fix-mac-packed-zip-parsing` 把 `._` 文件在 zip 解压阶段过滤了,LLM 只看到 3 个真实 docx→信心恢复
- 2 就地发现:(a) uvicorn `--log-level info` 不级联 `app.*` logger,本次 3 条 info 未取到但 DB 状态 + warning 缺席推导 path 3 成功结论成立;(b) `run_sampling.py` v1 `file_role` 字段取错已就地修复(不影响 confidence 结论)

### spec 同步
- **`openspec/specs/parser-pipeline/spec.md`** 加 1 Requirement(role_classifier 诊断日志契约)+ 3 scenarios(LLM 成功路径记 input shape + output mix / LLM 失败路径仅记 kind 不记 output mix / JSON 解析失败路径 warning 带 raw_text_head)
- **`docs/handoff.md`** 即本次更新

### 遗留到下次 / backlog
- **N3 收官**:不单开 hardening change;观测性代码作为回归武器存档;若日后大文档 role 退化病例重现,直接跑 `run_sampling.py` 采样归因
- **Follow-up(低优)**:uvicorn 默认 log config 不级联 app logger 到 INFO。可在 `backend/app/main.py` lifespan 顶部加 `logging.getLogger("app").setLevel(logging.INFO)`,或用 `--log-config yaml`。单独改不值得开 change,并入下一个触碰 main.py 的 change
- **Follow-up(低优)**:9 个 spec 文件 openspec validate 失败(pre-existing,与本 change 无关),可后续单独处理

---

## 2.bak_harden-async-infra 上一 session 关键决策(2026-04-23,`harden-async-infra` propose+apply+archive)

### 上游触发
上一 change `honest-detection-results` 归档时遗留 4 条基础设施鲁棒性 follow-up(F1/N5/N6/N7),合并成本 change。N3 LLM 大文档精度先 `/openspec-explore` 不 propose。

### propose 2 个产品决策(Q1-Q2 与用户对齐)
- **Q1 A**:坏 docx 触发 subprocess 崩溃时,该投标人该维度标 `skipped` + 中文文案"解析崩溃/超时,已跳过"(语义一脉相承 F2 证据不足,不引入新 failed 状态)
- **Q2 A**:LLM 超时单次 skipped 不做重试(explore N3 需要 timeout 可观测信号;重试作为 N3 后续 if needed)

### propose 中发现并纠正 3 处原 design 错误假设(P1 recon 触发方案 B 重写)
- **N7 现状**:`OpenAICompatProvider.complete()` **已经**有 `asyncio.wait_for` + 不抛异常,原 design "基类加超时壳 + LLMTimeoutError 抛异常" 误读 — 改为 "6 调用点审计 + 归一降级" + 全局 cap;丢弃 `LLMTimeoutError` 新类
- **AgentRunResult 无 skip_reason 字段**:skipped 状态在 DB 的 `AgentTask.status + summary` — 改为新 `AgentSkippedError` 异常 + `summary` 中文文案,零 schema 变更
- **F1 范围 2→3 agent**:共享 `get_cpu_executor()` 还被 `structure_similarity` 使用,scope 补齐避免留死角

### apply 现场决策(技术层,不问用户)
- **D1 run_isolated 不用 `with` context manager**:reviewer H1 apply 期 L1 实测暴露 `ProcessPoolExecutor.__exit__` 默认 `wait=True` 在 hang worker 下跟着卡;改 `try/finally: pool.shutdown(wait=False, cancel_futures=True) + 遍历 pool._processes 主动 terminate(0.3s)+ kill` — L1 `test_hang_workers_do_not_accumulate` 5 次 hang 验证通过
- **D4 `_cap_timeout` 双路径 + 三防御**:env `get_llm_provider()` 与 DB `get_llm_provider_db()` 都过 cap;None/0/负数 → 默认 cap(防 admin 误配 NULL 或 0 让 `asyncio.wait_for(timeout=0)` 立即超时);cache key `max(1, int(_cap_timeout(raw)))` 防 0<raw<1 被 int 截断为 0(reviewer M2)
- **H2 style.py 必须写 OA stub 再 raise AgentSkippedError**:reviewer H2 指出 raise 直接逸出导致 OA 行缺失 → ReportPage 按 OA 枚举会丢 style 维度条目;修复:`except AgentSkippedError as skip_exc: write_overall_analysis_row(...stub...); raise` 保持与 pre-N7 降级路径行为一致
- **H1 testdb loud-fail 双层防御**:reviewer H1 指出 `pytest_configure` 基于 sys.argv 子串匹配,跑全量时不触发 → `tests/e2e/conftest.py::_testdb_schema` session fixture 改为 loud `pytest.exit(code=2)` 兜底,不 early-return
- **M1 error_consistency 预防性 except AgentSkippedError**:N3 explore 可能让 call_l5 改抛,提前加 `except AgentSkippedError: raise` 写 OA stub 再逸出,防未来 regression
- **spec scenario 3.6 修正**:apply 审 judge.py 发现原 spec 声称 "judge LLM 超时 → indeterminate" 与代码不符(代码是 `fallback_conclusion + formula_level` 保留公式信号)→ 修 spec 对齐代码(证据充分但 LLM 失败时保留信号更正确,不强降 indeterminate)
- **run_isolated 通过 `loop.run_in_executor(per_call_pool, ...)` 而非 `pool.submit`**:保留测试层 monkeypatch `loop.run_in_executor` 的兼容性 — 生产仍 per-task 隔离,测试层不需重写既有 fixture

### 文档联动
- **`openspec/specs/pipeline-error-handling/spec.md`** 加 5 Req / 12 scenario(ProcessPool per-task 隔离 + AgentSkippedError 契约 + LLM 调用降级白名单 + LLM 全局 timeout 上限 + skipped 原因文案规范)
- **`docs/handoff.md`** 即本次更新
- **`backend/README.md`** 加 L2 测试容器化跑法 3 行

### 独立 reviewer 2 轮 pre-impl + 2 轮 post-impl:CONDITIONAL GO → GO(最终)
- 第 1 轮 pre-impl:H1 pool `with` hang / H2 image_reuse 不调 LLM / H3 env 路径 cap 漏 / M1-M5 全修(design + spec + tasks 二次更新;新增 ProcessPool worker 主动 kill / spec scenario 移除 image_reuse / env 路径纳入 cap / None/0/负数防御)
- 第 2 轮 post-impl(agent spawn + 用户独立并行):H1 conftest loud-fail 门漏勺 / H2 style.py OA 缺失回归 / H3 OA 写入差异 / M1 error_consistency 前置 except / M2 cache key 0<raw<1 / M3 L1 _has_sufficient_evidence skipped / L2/L4 → 全修(tests/e2e/conftest.py loud-fail / style.py 写 OA stub / error_consistency 前置 except / factory.py max(1,int) / 新增 L1 agentskipped_error_filtered / Windows platform slack + +1 degraded 文案)

### 遗留到下次 / backlog
- **N3 LLM 大文档精度退化**(159MB 文档 LLM role confidence 全 low 场景):本 change 提供了精细化 kind 日志(6 调用点)+ timeout 可观测上限,为 `/openspec-explore N3` 准备好诊断工具。建议下一步 explore
- **`test_xlsx_truncates_oversized_sheet` caplog 未捕获 warning**:pre-existing 问题,clean testdb 下暴露(dev DB 下可能因测试顺序巧合通过)。与本 change 无关,标 follow-up
- ~~**agent 全仓防御 except AgentSkippedError: raise**~~ ✅ 已被 `agent-skipped-error-guard` 落地(6 agent 加 guard + AST 元测试强制);stale 记录移除
- ~~**text_similarity `_DEGRADED_SUMMARY` 文案覆盖**~~ ✅ 已被 `test-infra-followup-wave2` Item 6 补强(DimensionRow 新增 2 case 覆盖真实 shape)

---

## 2.bak_honest-detection-results 上一 session 关键决策(2026-04-23,`honest-detection-results` propose+apply+archive)

### 上游触发
上一 change `fix-mac-packed-zip-parsing` 归档时列出的 10 条 follow-up,其中 5 条(F2/F3/N2/N4/N8)合并成本 change "用户看得到的诚实性"。F1/N5/N6/N7 基础设施鲁棒性下次做;N3 LLM 大文档精度先 explore。

### propose 5 个产品决策(Q1-Q5 已与用户对齐)
- **Q1 B**:"非 skipped 的信号型 agent 全部 score=0 且无铁证" → 证据不足
- **Q2 C**:`risk_level` 新增 `indeterminate` 枚举值(不用标志位,一次到位类型系统强制覆盖)
- **Q3 L2+L3+L5**:身份信息缺失显示位置 = 投标人详情 Drawer 顶部 + 报告 error_consistency 维度 + Word 导出降级文案(不做列表页/对比页)
- **Q4 a**:ROLE_KEYWORDS 10 个强烈建议新词(价格标/开标一览表/资信标/资信/业绩/类似业绩/企业简介/施工进度/进度计划)
- **Q5 B**:归档行用 `antd Collapse ghost` 默认折叠,复用 DimensionDetailPage 已有 pattern

### apply 现场决策(技术层,不问用户)
- **D1 信号型 agent 白名单**:SIGNAL_AGENTS 只含 text/section/structure/image/style/error_consistency,剔除 metadata_* + price_consistency("0 == 没异常" 不算无信号)—— 缓解"干净项目被误判 indeterminate"
- **D1 铁证短路**:PC.is_ironclad / OA.has_iron_evidence 任一为 True → 证据充分 True(避免 `total_score=85 + risk_level=indeterminate` 自相矛盾)
- **D4 identity_info_status 放 ORM @property + from_attributes=True**:而不是 Pydantic computed_field(BidderSummary 没 identity_info 字段,computed_field 会 AttributeError)
- **D5 前端 TS 收紧路径**:`Record<RiskLevel, ...>` + 删 `| string` 逃生门 + 删运行期 `?? RISK_META.low` — 第 1 轮 reviewer 指出原"TS 强制覆盖"承诺是虚假保证,收紧后才真成立
- **D7 ROLE_KEYWORDS 同步约束降级**:SSOT=role_keywords.py;defaults 允许短子串(故意不强求值相等);弱一致性=defaults 每词 MUST 是 SSOT 某词的子串;prompts.py 不进机械测试(自然语言无可靠提取规则),靠 docstring 人工 review
- **D10 report_ready vs project.status 顺序**:INSERT AnalysisReport → UPDATE project.status 之间有 ~几十毫秒窗口,前端 MUST 以 report_ready 为权威拉取判据(spec scenario 明确)
- **I-3 补 DimensionRow 孤立组件测试**:第 3 轮 reviewer 指出 Task 5.7/6.4 降级 manual 后, `<Alert data-testid="dimension-identity-degraded">` 零自动化覆盖 — export DimensionRow + 4 case 孤立 render 测试

### 文档联动
- **`openspec/specs/detect-framework/spec.md`** 改:"综合研判骨架" 插 step4 + 加 scenario;"检测状态快照 API" 加 report_ready + 4 scenario
- **`openspec/specs/detect-framework/spec.md`** 加:"证据不足判定规则" / "AnalysisReport risk_level 新增 indeterminate" 两 Requirement
- **`openspec/specs/parser-pipeline/spec.md`** 改 "角色关键词兜底规则":加三副本同步约束 + 10 新词 scenario + authorization 条说明
- **`openspec/specs/report-view/spec.md`** 加 3 Req
- **`openspec/specs/report-export/spec.md`** 加 1 Req
- **`docs/handoff.md`** 即本次更新

### 3 轮独立 review 均 CONDITIONAL GO → GO(最终)
- 第 1 轮:TS 强制覆盖虚假保证 / BidderSummary 无 identity_info / 铁证 vs indeterminate 冲突 / 三副本 set 相等不可靠 — 全修
- 第 2 轮:BidderSummary computed_field AttributeError / _ALLOWED_RISK_LEVELS 漏改 / Word 模板 low/medium/high 回归 / report_ready vs project_status 顺序 — 全修
- 第 3 轮:useDetectProgress SSE risk_level 漏 indeterminate / report_ready 前端无消费点 / 2way sync 弱一致性缺失 / DimensionRow 零自动化 — 全修

### 遗留到下一 change(`harden-async-infra`)
- F1 ProcessPool per-task 进程隔离
- N5 testdb 容器化
- N6 `make_gbk_zip` fixture 重写
- N7 LLM provider `.complete()` 统一 `asyncio.wait_for`

N3 LLM 大文档精度先 `/openspec-explore` 再决定。11.3 Manual 观测建议:跑全量历史项目统计 indeterminate 占比,>5% 触发 design 复审。

---

## 2.bak_fix-mac-packed-zip-parsing 上一 session 关键决策(2026-04-23,`fix-mac-packed-zip-parsing` propose+apply+archive)

### 案例触发
- 真实 A/B zip(`e2e/artifacts/supplier-ab/supplier_A.zip` 166MB / `supplier_B.zip` 9.8MB,macOS Archive Utility 打包)暴露:parser 流水线**静默降级为无意义结果**(bid_documents.role 全 None、identity_info 全 null、检测报告"全零 + 低风险无围标"误导结论)
- 用户感知:"流程跑不同/卡住了" — 实则流水线跑完但结果全 0

### propose 阶段已敲定(产品/范围级决策)
- **A/B/C 选项分三层**:A 最小(只修 macOS 那批)、B 完整黑名单(+Windows/Office/VCS,**推荐选中**)、C 白名单严打(被否决:扩展名白名单过不掉 `~$x.docx` 这类恰好是 .docx 的临时文件)
- **区分"垃圾丢弃" vs "不支持但告知"**:打包垃圾 → 静默丢弃不产 bid_documents 行;非业务扩展名 → 保留 skipped 反馈用户
- **identity_info 不做规则兜底**:保持 spec 原意("避免精度差导致污染"),follow-up 由 UI/报告侧显示"识别信息缺失"文案

### apply 现场决策
- **保留 engine.py 既有 GBK 启发式 + 后置 UTF-8 校验**(而非整段删改):零回归路径,Windows GBK 包不受影响
- **`classify_by_keywords` 契约变更** None on miss(原返 "other"):便于上层两级兜底区分"命中 other" vs "未命中";同步更新唯一 production 调用点 + 2 个测试文件
- **fixture scope-safe 清理**:共享 dev DB 里有 project 226 的老数据,既有 `test_parser_llm_role_classifier.py` 的 `DELETE WHERE id>0` 会和 FK 冲突;改为按 `User.username` 前缀过滤只删本测试的 seed
- **端到端修 `_phase_extract_content`**(范围外但必要):真实 A/B 验收暴露 pipeline 把 .zip 归档行也扔给 `extract_content`,标成"未知文件类型 .zip" 覆盖我写入的 "已过滤 N 个" 审计文本;加一行 `file_type.in_([".docx",".xlsx"])` 过滤 + 回归测试
- **L2 fixture 手工构造 UTF-8-no-flag ZIP**:Python stdlib `zipfile` 对非 ASCII 文件名会强制置位 bit 11,无法原生模拟 macOS 无 flag 场景;手写本地文件头+中心目录+EOCD 精确控制 flag
- **manual 凭证用 JSON 代截图**:CLI 环境无 GUI,`verify.py` 调真 LLM 跑完整流程把 `bidders_before_detect / documents_A / documents_B / analysis_status / report` JSON 落盘到 `e2e/artifacts/supplier-ab/after-fix/`

### 文档联动
- **`openspec/specs/file-upload/spec.md`** 改 "压缩包安全解压" Requirement,+6 新 Scenario
- **`openspec/specs/parser-pipeline/spec.md`** 改 "LLM 角色分类与身份信息提取" + "角色关键词兜底规则" 两个 Requirement
- **`docs/handoff.md`** 即本次更新

### 发现但 **不在本次 change 范围** 的遗留问题(10 条)
参见 archive 目录 `openspec/changes/archive/2026-04-23-fix-mac-packed-zip-parsing/design.md` §5"Open Questions" 上下文。总览 + 优先级:
- **F2 高**:judge LLM 全零/全 skipped 时仍给"无围标"误导结论 — 应返"证据不足"
- **F1 中**:ProcessPool 崩溃兜底(per-task 进程隔离);A/B 案例靠垃圾过滤"绕过"但根因没修
- **F3 中**:identity_info NULL 时 UI/报告侧文案降级
- **N3 中**:大文档(如 161MB docx)下 LLM role_classifier 精度退化(A 全走兜底 low,B 全 high)— 需先开日志调查
- **N5 中**:共享 dev DB 污染导致 `pytest tests/e2e/` 全量跑不动 — testdb 容器化
- **N7 低-中**:LLM provider `.complete()` 没统一 `asyncio.wait_for`
- **N2 低-中**:`ROLE_KEYWORDS` 补 "价格标"/"资信标"(A 的"价格标/资信标"因此没命中 pricing/qualification)
- **N4 低**:analysis completion 与 report 生成时序不对齐(需加 `report_ready` 字段)
- **N6 低**:`make_gbk_zip` fixture 实际产出不是声称的东西(flag 被强制置位)— 重写
- **N8 低**:归档行(.zip)在 UI 的语义模糊 — 按 file_type 折叠

---

## 2.bak_admin-llm-config 上一 session 关键决策(2026-04-20,`admin-llm-config` propose+apply+archive)

### propose 阶段已敲定(5 产品级决策)

- **Q1 B dashscope + openai + custom**:白名单 3 种,custom = OpenAI 兼容端点
- **Q2 B 末 4 位保留**:`sk-****abc1`;短于 8 位固定 `sk-****` 占位
- **Q3 B 做测试连接按钮**:发 `"ping"` + max_tokens=1,最省 token
- **Q4 B 三层优先级**:DB > env > 代码默认;保持旧部署兼容
- **Q5 B 指纹哈希 cache + PUT 失效**:(provider, key, model, base, timeout) 作 key,PUT 后清空

### apply 现场决策

- **audit_log 暂不写 admin-llm 更新**:`AuditLog.project_id` 非空,系统级配置不挂项目;Follow-up 改 project_id nullable 或新建 SystemAuditLog
- **factory `get_llm_provider()` 保持同步签名 + env 路径**:11 个 Agent / judge / pipeline 现有调用零改动;新增 `get_llm_provider_db(session)` 异步路径供后续逐步切换
- **`@lru_cache` 换成 dict 指纹缓存**:上限 3,FIFO 淘汰,防病态输入撑爆
- **Tester `max_tokens=1` + timeout 强制 ≤10s**:防 UI 卡死
- **前端 api_key 空白不传**:占位符显示脱敏值,空白提交 → 后端保持旧值

### 文档联动

- **`openspec/specs/admin-llm/spec.md`** 新建:6 Req / 14 Scenario
- **`e2e/artifacts/admin-llm-2026-04-20/README.md`** L3 手工凭证
- **`docs/handoff.md`** 即本次更新

---

## 2.bak_C17 上一 session 关键决策(2026-04-16,C17 `admin-users` propose+apply)

- Q1 A 仅全局级 SystemConfig / Q2 A 覆盖写 + 恢复默认 / Q3 A admin 手动创建 / Q4 A §8 最小集
- L3 手工凭证:`e2e/artifacts/c17-2026-04-16/README.md`

---

## 2.bak_C15 上上一 session 关键决策(2026-04-16,C15 `report-export` propose+apply)

### propose 阶段已敲定(4 产品级决策)

- **Q1 C Word 模板两者结合**:内置默认 + 用户上传可覆盖 + 上传坏掉回退内置
- **Q2 D 复核粒度组合**:整报告级(必须)+ 维度级(可选)
- **Q3 A 独立 `audit_log` 表全字段**
- **Q4 D 异步 + 预览链接 + 三兜底**

### apply 阶段就地敲定(重要现场决策 B2)

- **design D4 改 B2**:原 design 假设复用 `async_tasks`,apply 发现侵入大;就地改独立 `export_jobs` 表(14 字段)

---

## 2.bak_C14 上一 session 关键决策(2026-04-16,C14 propose+apply+archive)

- Q1 B 预聚合结构化摘要 / Q2 A 公式兜底 / Q3 B 可升不可降+铁证 85 守护 / Q4 C 不做跨项目共现 / Q5 C 降级模板+前缀哨兵
- apply:AgentRunResult 字段名修正 / e2e autouse fixture / fallback 前缀约束 / summarize 铁证无条件入 top_k

---

## 2.bak_C13 上一 session 关键决策(2026-04-15,C13 propose+apply+archive)

- Q1 合并 / Q2 (A) L-5 铁证 / Q3 (C) MD5+pHash 双路 / Q4 (C) L-8 全 LLM / Q5 零新增依赖
- apply:不扩 AgentRunResult 改走 OA evidence 顶层 / DocumentText 行级 SQL / imagehash int64 cast

---

## 3. 待确认 / 阻塞

- 无硬阻塞,**M4 完成(3/3),全部 17 个 change 已归档**
- **Follow-up(C16)**:字符级 diff / price evidence 对齐 / 对比页面导出
- **Follow-up(C17)**:元数据白名单已通过 admin 规则配置可编辑（✅ 已解决）；按维度分 Tab 的完整配置 UI（第二期）
- **Follow-up(C15)**:用户模板上传 UI / PDF 导出 / 批量导出 / audit 过滤器 / 导出历史页
- **Follow-up(C14)**:跨项目历史共现 / DIMENSION_WEIGHTS 实战调参 / L-9 prompt N-shot 精调
- **Follow-up(持续)**:Docker kernel-lock 未解(C3~C17 L3 全延续手工凭证)
- **Follow-up(持续)**:生产部署前 env 覆盖全清单
- **Follow-up(产品决策搁置,2026-04-22)**:投标包内若报价单为 `.doc/.docx` 而非 `.xlsx`,当前链路**静默 skip**(无报错),导致 price_consistency 维度漏检
  - 现状代码位置:`run_pipeline.py:_find_pricing_xlsx` 硬过滤 `.xlsx` / `fill_price.py` 仅走 `extract_xlsx` / `price_consistency.py` preflight 找不到时 skip
  - 已评估两条路径并**搁置**:
    - 最小止血(1 天):改为显式 failed + UI 提示"报价单非 xlsx 格式,需人工"
    - 完整方案(6-8 天):抽象 tabular region + docx 表抽取 + LLM 兜底 C(详见此 session 讨论记录)
  - 触发重启条件:业务侧反馈 docx 报价单出现频率显著上升,或出现因此漏检的围标 case

---

## 4. 下次开工建议

**一句话交接**:
> **M4 完成,全部 17 个 change 已归档。** C15 报告导出 + C16 对比视图 + C17 用户管理/规则配置 = M4 可交付。系统具备完整的上传→解析→检测→报告→导出→对比→管理能力。下一步：M4 演示级交付凭证 + follow-up 规划（第二期 backlog 整理）。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M4 已完成(3/3),C17 admin-users 已 archive + push。
全部 17 个 change（C1~C17）已归档,系统达到可交付状态。
下一步:
  1. M4 演示级交付凭证(execution-plan §4 要求:Word 报告示例 + 管理操作截图)
  2. follow-up backlog 整理(C14~C17 累积的 follow-up 项)
  3. 第二期规划(US-9.2 按维度分 Tab / US-10 LLM 配置 / 跨项目历史共现 等)
请先读 docs/handoff.md 和 docs/execution-plan.md §4~§6 确认现状。
也检查 memory 和 claude.md。
```

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-23 | **`fix-admin-users-page-flaky-test` 归档**:前端 `AdminUsersPage 创建用户成功` 全量跑 flaky 修复。`userEvent.setup({ delay: null })` 移除 keystroke microtask + test-level `timeout=15000ms` 兜底(apply 期实测 D1 单独 3/3 fail,主备同出才稳定)。前端 L1 **114/114** 连续 3 次稳定;`pipeline-error-handling` +1 Requirement "前端交互测试 timing 契约";scope 锁死只修 1 站点不批改其他 14+ `userEvent.setup()` 历史站点 |
| 2026-04-23 | **`test-infra-followup-wave2` 归档**:5 项测试/诊断基础设施 follow-up 合 1 处理 —— Item 1(🔴 real bug)alembic/env.py 加 `disable_existing_loggers=False` 修复 L2 `test_xlsx_truncates_oversized_sheet` caplog 丢警告(L2 从 280+1fail → **281/281 全绿**);Item 2 engine except 顺序正则→AST(复用 agent-skipped-error-guard pattern,契约精修到 `_mark_failed` body);Item 3 `run_isolated._processes` 访问加 try/except future-proof Py 3.14+(apply 期推翻 mock 路径,改静态源码断言);Item 4 main.py lifespan setLevel `app` logger INFO 解决 uvicorn 不级联;Item 6 DimensionRow +2 case 覆盖 text_sim degraded 非 skipped 真实 shape;`pipeline-error-handling` spec +1 Requirement 锁 3 稳定契约;handoff 2 条 stale 项清理;零产品行为变化 |
| 2026-04-23 | **`llm-classifier-observability` 归档**:N3 LLM 大文档精度退化收官。`role_classifier.py` 加 3 条 info 诊断日志(input shape / output confidence mix / invalid JSON raw_text_head)+ `_looks_mojibake` heuristic + 1 ADDED Requirement 进 parser-pipeline spec;L1 新增 11 case 全绿,测试总 1011 绿;Task 3.3 manual 真 LLM 双采样(ark provider,~¥0.2)证明 N3 原始症状不再复现(A/B 2 轮均 high=3 low=0 完全一致),根因 H2a 已被 `fix-mac-packed-zip-parsing` 顺带修掉;观测性代码作未来回归武器存档 |
| 2026-04-23 | **`harden-async-infra` 归档**:F1 ProcessPool per-task 隔离(3 agent × `run_isolated` + finally terminate/kill)+ N7 LLM 6 调用点降级归一 + `factory._cap_timeout` 两路径 + None/0/负数防御 + cache key `max(1, int())`  + N5 testdb 容器化(`docker-compose.test.yml` + conftest 双层 loud-fail)+ N6 `make_gbk_zip` 手写字节重写(old stdlib `zipfile` bit 11 强制置位致 fix-mac-packed-zip-parsing 自动回归失效)+ 集中 `errors.py` 7 常量 + `AgentSkippedError` + style/error_consistency 写 OA stub 保前端维度完整;L1 988 + L2 274/275 + 前端 12/12 全绿;合并 1268/1269 in 3:17;2 轮独立 reviewer + 2 轮 post-impl 全吸收(H1 pool hang 实质修 / H2 OA stub / M2 cache key 0 塌陷 等) |
| 2026-04-23 | **`agent-skipped-error-guard` 归档**:预防性加固 harden-async-infra 的 reviewer MEDIUM latent risk(其他 agent 未来加 AgentSkippedError 抛出路径时被通用 except 静默吞成 failed)。6 个 agent(metadata_author/machine/time / price_consistency/anomaly / image_reuse)在 `except Exception` 前加 `except AgentSkippedError: raise`;新增 AST-based L1 元测试 `test_agent_except_skipped_guard.py` 扫 `agents/*.py` 的所有 `async def run()` 函数,静态强制"有 broad except 必须前置 except AgentSkippedError" — 防未来新 agent 忘加或重构破坏契约;反向验证(临时删 guard → 测试 assert 失败,精准定位文件行号)通过;L1 1000/1000 绿(+12 参数化 + 1 sanity);零产品行为变化 |
