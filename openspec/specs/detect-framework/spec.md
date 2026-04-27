# detect-framework Specification

## Purpose

异步检测框架:启动检测 API + 10 Agent 注册表与自检 + asyncio.gather 并行调度 + SSE 进度推送 + 综合研判占位 + 通用任务表(extract/content_parse/llm_classify/agent_run 4 subtype 统一心跳追踪与重启恢复)。本 capability 把 C3~C5 已解析完成的项目推进到启动检测 → 10 维度并行产出评分 → 报告骨架端到端通路,为 C7~C13 各真实 Agent 提供稳定 contract(name / agent_type / preflight 签名);C7+ 各 change 只替换对应 Agent 的 `run()` 实现,不动框架。
## Requirements
### Requirement: 启动检测 API

系统 SHALL 提供 `POST /api/projects/{pid}/analysis/start` 端点,允许 owner(reviewer)或 admin 对自己有权访问的项目启动一轮检测。启动前 MUST 通过完整前置校验(见 "检测启动前置校验" Requirement);校验通过后:
1. 分配 `version = max(agent_tasks.version WHERE project_id=?, 0) + 1`(失败轮次的 version **占位不复用**)
2. 批量 INSERT AgentTask 行:`C(n,2) × 7 (pair 型) + 3 (global 型)` 条(`n = 项目 bidder 数`),初始 status = `pending`
3. UPDATE project.status = `'analyzing'`
4. `asyncio.create_task(run_detection(project_id, version))` 异步启动调度
5. 响应 **201**,body = `{"version": int, "agent_task_count": int}`

reviewer 启动非自己的项目 MUST 返回 404(不泄露项目存在性);admin 可启动任何未软删项目。

#### Scenario: 2 个投标人启动检测成功

- **WHEN** reviewer A 对自己项目(2 bidder,均 identified 态)发送 `POST /api/projects/{pid}/analysis/start`
- **THEN** 响应 201 + `{"version": 1, "agent_task_count": 10}`(1 pair × 7 + 3 global);DB 中 10 条 AgentTask 行 `status='pending'`;project.status = `'analyzing'`

#### Scenario: 3 个投标人启动检测

- **WHEN** 项目有 3 bidder 均 identified → 启动
- **THEN** 响应 201 + `{"version": 1, "agent_task_count": 24}`(3 pair × 7 + 3 global = 21 + 3 = 24)

#### Scenario: version 占位不复用

- **WHEN** 项目上一轮检测失败(agent_tasks 有 version=1 但全 failed/timeout)且 project.status 回到 ready → 再次启动
- **THEN** 响应 201 + `{"version": 2, ...}`(不复用 version=1)

#### Scenario: reviewer 启动他人项目返回 404

- **WHEN** reviewer A 对 B 的项目发送启动请求
- **THEN** 响应 404;不创建任何 AgentTask 行

#### Scenario: admin 启动任意项目

- **WHEN** admin 对任一 reviewer 的 ready 态项目发送启动请求
- **THEN** 响应 201

---

### Requirement: 检测启动前置校验

系统 MUST 在启动检测前按顺序校验以下前置条件,任一失败立即返 400(或 409),不创建 AgentTask 行,不变更 project.status:

1. 项目未软删(否则 404)
2. 权限(reviewer 仅自己 / admin 任意;否则 404)
3. `project.status ∈ {'ready', 'completed'}`(`analyzing` → 409;`draft / parsing` → 400 "项目未就绪")
4. bidder 数 ≥ 2(否则 400 "至少需要2个投标人")
5. 所有 bidder.parse_status ∈ 终态集 `{identified, priced, price_partial, identify_failed, price_failed, skipped, needs_password}`(否则 400 "请等待所有文件解析完成")

#### Scenario: 投标人数不足返回 400

- **WHEN** 项目仅 1 bidder → 启动
- **THEN** 响应 400,body 含 "至少需要2个投标人";无 AgentTask 创建

#### Scenario: 解析未完成返回 400

- **WHEN** 项目 2 bidder,其中 1 个 `parse_status='identifying'`(进行中)→ 启动
- **THEN** 响应 400,body 含 "请等待所有文件解析完成"

#### Scenario: 项目 draft 态返回 400

- **WHEN** 项目 `status='draft'` → 启动
- **THEN** 响应 400,body 含 "项目未就绪"

#### Scenario: 包含部分失败态的 bidder 可启动

- **WHEN** 项目 2 bidder:1 个 identified,1 个 identify_failed(终态)→ 启动
- **THEN** 响应 201(identify_failed 属终态,允许启动;Agent 自检会 skip 该 bidder 涉及的 pair)

---

### Requirement: 启动检测幂等(analyzing 态 409)

`POST /api/projects/{pid}/analysis/start` 在项目 `status='analyzing'` 时 MUST 返回 **409**,body 含 `{"current_version": int, "started_at": iso8601}`。不创建新 AgentTask 行,不变更 project.status。

#### Scenario: analyzing 态重复启动返 409

- **WHEN** 项目正在 analyzing(version=2,started_at=T0)→ 再次发送启动请求
- **THEN** 响应 409 + `{"current_version": 2, "started_at": T0}`;DB 中 AgentTask 行数不变

---

### Requirement: AgentTask 数据模型

`agent_tasks` 表 MUST 包含以下字段:
- `id INTEGER PK`
- `project_id FK → projects.id NOT NULL`
- `version INTEGER NOT NULL`
- `agent_name VARCHAR(64) NOT NULL`(10 种之一)
- `agent_type VARCHAR(16) NOT NULL`(`pair | global`)
- `pair_bidder_a_id INTEGER NULL FK → bidders.id`
- `pair_bidder_b_id INTEGER NULL FK → bidders.id`
- `status VARCHAR(16) NOT NULL DEFAULT 'pending'`(pending / running / succeeded / failed / timeout / skipped)
- `started_at TIMESTAMPTZ NULL`
- `finished_at TIMESTAMPTZ NULL`
- `elapsed_ms INTEGER NULL`
- `score NUMERIC(6,2) NULL`(0-100)
- `summary VARCHAR(500) NULL`
- `error TEXT NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`

约束:
- 索引 `(project_id, version)` 支撑快照查询
- 索引 `(status, started_at)` 支撑 scanner 扫描
- PostgreSQL CHECK 约束:`(agent_type='pair' AND pair_bidder_a_id IS NOT NULL AND pair_bidder_b_id IS NOT NULL) OR (agent_type='global' AND pair_bidder_a_id IS NULL AND pair_bidder_b_id IS NULL)`;SQLite 退化为应用层保证

#### Scenario: alembic upgrade 创建表

- **WHEN** 在 0004 后执行 `alembic upgrade head`
- **THEN** `agent_tasks` 表存在,所有列、索引、CHECK 约束按 spec 建立

#### Scenario: pair 型 AgentTask 插入

- **WHEN** INSERT `agent_type='pair', pair_bidder_a_id=10, pair_bidder_b_id=11`
- **THEN** INSERT 成功

#### Scenario: global 型 AgentTask 插入

- **WHEN** INSERT `agent_type='global', pair_bidder_a_id=NULL, pair_bidder_b_id=NULL, agent_name='error_consistency'`
- **THEN** INSERT 成功

---

### Requirement: 10 Agent 注册表

后端 MUST 在 `app/services/detect/registry.py` 提供 `AGENT_REGISTRY: dict[str, AgentSpec]` + `register_agent(name, agent_type, preflight)` 装饰器。`AgentSpec` 包含 4 字段:`name / agent_type / preflight / run`。

系统启动后 `AGENT_REGISTRY` MUST 恰好含 **11** 条目,name 为:
- pair 型 7 个:`text_similarity / section_similarity / structure_similarity / metadata_author / metadata_time / metadata_machine / price_consistency`
- global 型 **4** 个:`error_consistency / style / image_reuse / price_anomaly`

C6 阶段 10 Agent 的 `run()` 为 dummy;C7~C11 先后替换 pair 型 7 个 Agent 与 global 型 `price_anomaly`(C12 新增);**C12 归档后 `price_anomaly` 直接带真实 run 注册,不经 dummy 阶段**。其余 3 global Agent(`error_consistency / style / image_reuse`)`run()` 继续走 dummy,直至 C13 替换。

`EXPECTED_AGENT_COUNT` 常量 MUST 保持与注册表实际条目数一致(本 change 归档后 = 11)。

#### Scenario: 注册表含 11 Agent

- **WHEN** 加载 `app.services.detect.agents.*` 模块后读 `AGENT_REGISTRY`
- **THEN** 恰好 11 条目,7 pair + 4 global 分类正确;其中 `price_anomaly` agent_type='global'

#### Scenario: 重复注册同名 Agent 抛错

- **WHEN** 再次用已存在 name 调 `register_agent` 装饰器
- **THEN** 模块加载期抛 `ValueError("agent already registered")`

#### Scenario: 未知 name 查询返 None

- **WHEN** `AGENT_REGISTRY.get("unknown")`
- **THEN** 返 None(标准 dict 行为)

---

### Requirement: Agent preflight 前置条件自检

每个 Agent MUST 实现 `async def preflight(ctx: AgentContext) -> PreflightResult` 函数;返 `PreflightResult(status: Literal["ok", "skip", "downgrade"], reason: str | None)`。

自检规则:
- `text_similarity / section_similarity / structure_similarity`:pair 双方均有同角色文档 → ok;否则 skip "缺少可对比文档"
- `metadata_author / metadata_time / metadata_machine`:pair 双方均有 metadata(对应字段非空)→ ok;否则 skip "未提取到元数据"
- `price_consistency`:pair 双方均 `parse_status='priced'` 且 price_items 非空 → ok;否则 skip "未找到报价表"
- `price_anomaly`:项目下 `parse_status='priced'` 且有 price_items 的 bidder 数 ≥ `PRICE_ANOMALY_MIN_SAMPLE_SIZE`(默认 3)→ ok;否则 skip "样本数不足,无法判定异常低价"
- `error_consistency`:pair 双方 identity_info 非空 → ok;任一方空 → **downgrade "降级检测,建议补充标识信息后重新检测"**(不 skip,后续 run 用 bidder.name 关键词交叉)
- `style`:≥2 bidder 有同角色文档 → ok;否则 skip "缺少可对比文档"
- `image_reuse`:≥2 bidder 提取到图片 → ok;否则 skip "未提取到图片"

preflight 返 `skip` → AgentTask status = `skipped`,reason 写入 `summary`,不执行 run。
preflight 返 `downgrade` → ctx.downgrade = True,正常执行 run(Agent 内部决定降级语义)。
preflight 抛异常 → 视为 `skip "preflight 异常: <error>"`,不视为 failed(preflight 是 Agent 自检,不算"运行失败")。

#### Scenario: 缺少可对比文档 skip

- **WHEN** text_similarity preflight:pair bidder_a 有 technical 文档,bidder_b 无 technical 文档
- **THEN** 返 `PreflightResult(status='skip', reason='缺少可对比文档')`

#### Scenario: error_consistency 降级不 skip

- **WHEN** error_consistency preflight:bidder_a.identity_info = None,bidder_b.identity_info 有值
- **THEN** 返 `PreflightResult(status='downgrade', reason='降级检测...')`;后续 run 被调用时 ctx.downgrade = True

#### Scenario: price_anomaly 样本不足 skip

- **WHEN** price_anomaly preflight:项目下只有 2 家 bidder 成功解析报价(`parse_status='priced'` 且 price_items 非空)
- **THEN** 返 `PreflightResult(status='skip', reason='样本数不足,无法判定异常低价')`

#### Scenario: preflight 异常视为 skip

- **WHEN** preflight 内部抛 Exception
- **THEN** AgentTask status=`skipped`,summary 含 "preflight 异常" 前缀

---

### Requirement: Agent 并行调度与单 Agent 超时

系统 MUST 使用 `asyncio.gather(*coros, return_exceptions=True)` 并行执行所有 AgentTask 的 coroutine;单 Agent MUST 用 `asyncio.wait_for(run, timeout=AGENT_TIMEOUT_S)` 限制最大运行时间,默认 `AGENT_TIMEOUT_S = 300`(5 分钟)。

单 Agent 执行流程:
1. 写 AgentTask.started_at = now(), status = `running`
2. 调 `spec.preflight(ctx)` → 若 skip 立即返
3. 调 `await asyncio.wait_for(spec.run(ctx), AGENT_TIMEOUT_S)`
4. 成功 → status=`succeeded`, score / summary 写入,finished_at / elapsed_ms 更新
5. 超时 → status=`timeout`, summary="Agent 超时 (>5min)"
6. 其他异常 → status=`failed`, error=异常前 500 字

每个 Agent 执行外层包 `async with track(subtype='agent_run', entity_type='agent_task', entity_id=task.id):` 写 async_tasks 心跳。
每个 Agent 完成后(无论成功/失败/跳过/超时)MUST 向 progress_broker publish `agent_status` 事件。

#### Scenario: 单 Agent 成功

- **WHEN** text_similarity dummy run 返 score=42.5, summary="dummy result"
- **THEN** AgentTask status=`succeeded`, score=42.5, elapsed_ms > 0;broker 收到 agent_status 事件

#### Scenario: 单 Agent 抛异常不影响其他

- **WHEN** 1 个 Agent run 抛 `ValueError("boom")`;其他 9 个正常
- **THEN** 该 Agent AgentTask status=`failed`, error="ValueError: boom";其他 9 个正常完成

#### Scenario: 单 Agent 超时

- **WHEN** AGENT_TIMEOUT_S=0.1,dummy run 固定 sleep 1s
- **THEN** 该 Agent status=`timeout`, summary 含 "超时"

---

### Requirement: 全局检测超时

整个检测 MUST 用 `asyncio.wait_for(asyncio.gather(...), timeout=GLOBAL_TIMEOUT_S)` 限制,默认 `GLOBAL_TIMEOUT_S = 1800`(30 分钟)。全局超时时:
1. 所有仍 `running` 的 AgentTask UPDATE → status=`timeout`
2. 仍 `pending` 的 AgentTask UPDATE → status=`timeout`
3. 继续触发综合研判生成 AnalysisReport(不因超时跳过报告)

#### Scenario: 全局超时

- **WHEN** GLOBAL_TIMEOUT_S=1,有 3 Agent 各 sleep 5s
- **THEN** 3 Agent status=`timeout`;AnalysisReport 仍生成(含各维度程序化得分 0 + "AI 研判暂不可用")

---

### Requirement: 综合研判骨架与评分公式

所有 AgentTask 进终态(succeeded/failed/timeout/skipped)后,系统 MUST 调 `judge.judge_and_create_report(project_id, version)`,按以下流水线产出 `AnalysisReport`:

1. 加载该 version 所有 `PairComparison` + `OverallAnalysis` 行
2. 纯函数 `compute_report(pair_comparisons, overall_analyses) -> (formula_total, formula_level)` 先算公式层结论:
   a. 每维度取跨 pair/global 最高分 `per_dim_max[dim] = max(all scores for dim)`
   b. `formula_total = sum(per_dim_max[dim] * DIMENSION_WEIGHTS[dim] for dim in 11 维度)`,四舍五入 2 位
   c. 铁证升级:任一 `pc.is_ironclad=true` 或任一 `oa.evidence_json["has_iron_evidence"]=true` → `formula_total = max(formula_total, 85.0)`
   d. `formula_level`:formula_total ≥ 70 → `high`;40-69 → `medium`;< 40 → `low`
3. **[新增] 补写 pair 类维度 OA 行**:对 7 个 pair 类维度(text_similarity / section_similarity / structure_similarity / metadata_author / metadata_time / metadata_machine / price_consistency),系统 MUST 在 AnalysisReport INSERT 之前写入 `overall_analyses` 行,每维度一行。OA 行内容:
   - `score` = 该维度的 `per_dim_max[dim]`(已在步骤 2a 计算)
   - `evidence_json` = `{"source": "pair_aggregation", "best_score": <float>, "has_iron_evidence": <bool>, "pair_count": <int>, "ironclad_pair_count": <int>}`
   - 写入 MUST 幂等:若 `(project_id, version, dimension)` 已有 OA 行则跳过
4. **[新增] 证据不足前置判定**(honest-detection-results):调 `_has_sufficient_evidence(agent_tasks, pair_comparisons, overall_analyses)`(含铁证短路 + SIGNAL_AGENTS 白名单,见"证据不足判定规则"Requirement);若返 False → **跳过步骤 5-7** 的 LLM 调用,直接 `final_total=formula_total`、`final_level='indeterminate'`、`llm_conclusion="证据不足,无法判定围标风险(有效信号维度全部为零)"`,跳到步骤 8
5. 构造 **L-9 LLM 综合研判** 输入(同原步骤 3,编号后移)
6. LLM 调用(同原步骤 4)
7. **clamp 守护**(同原步骤 5)
8. **失败兜底**(同原步骤 6;对 indeterminate 分支不触发因已跳过 LLM)
9. INSERT AnalysisReport(同原步骤 7)
10. UPDATE `project.status = 'completed'` / `project.risk_level`(同原步骤 8,支持 indeterminate)
11. broker publish `report_ready`(同原步骤 9)

检测完成后,`overall_analyses` 表 MUST 包含该 version 的全部 11 个维度(4 global + 7 pair),使维度级复核 API 对所有维度可用。

`compute_report` 纯函数签名和语义不变。OA 写入在 `judge_and_create_report` 异步函数内完成。

权重 `DIMENSION_WEIGHTS` 合计 = 1.00,本 change 不调整。

#### Scenario: pair 类维度 OA 行写入

- **WHEN** 2 个投标人检测完成,text_similarity agent 写了 1 行 PairComparison(score=60, is_ironclad=false)
- **THEN** judge 阶段写入 text_similarity 的 OA 行:score=60, evidence_json.source="pair_aggregation", evidence_json.has_iron_evidence=false, evidence_json.pair_count=1

#### Scenario: pair 类铁证维度 OA 行写入

- **WHEN** 3 个投标人检测完成,metadata_author agent 写了 3 行 PairComparison(A-B: score=100 ironclad=true, A-C: score=80 ironclad=false, B-C: score=100 ironclad=true)
- **THEN** judge 阶段写入 metadata_author 的 OA 行:score=100, evidence_json.has_iron_evidence=true, evidence_json.pair_count=3, evidence_json.ironclad_pair_count=2

#### Scenario: OA 写入幂等

- **WHEN** judge_and_create_report 被重复调用(如重试)
- **THEN** 第二次调用不重复写入 OA 行;已有 OA 行保持不变

#### Scenario: 检测完成后 OA 行总数

- **WHEN** 任意检测版本完成(不论 agent 成功/失败/跳过)
- **THEN** overall_analyses 表该 version 恰好有 11 行(每维度一行);维度级复核 API 对全部 11 维度返回 200

#### Scenario: LLM 成功升分跨档

- **WHEN** 11 Agent 跑完,formula_total=65(medium)、无铁证;LLM 返回 `{suggested_total: 75, conclusion: "三维度共振...", reasoning: "..."}`
- **THEN** final_total=75,final_level=`high`(跨档);AnalysisReport.llm_conclusion = LLM 返回的 conclusion 文本;project.risk_level='high'

#### Scenario: LLM 试图降铁证分被守护

- **WHEN** formula_total=88(high + 任一 PC.is_ironclad=true),LLM 返回 `{suggested_total: 60, conclusion: "...", reasoning: "..."}`
- **THEN** clamp step1 max(88, 60)=88;step2 铁证守护 max(88, 85)=88;final_total=88,final_level=`high`;LLM 降分完全无效

#### Scenario: 证据不足触发 indeterminate 分支

- **WHEN** 11 个 AgentTask 里 3 个 skipped + 8 个 succeeded 但 score 全零;judge 运行
- **THEN** LLM 不被调用;AnalysisReport.risk_level='indeterminate'、total_score=0、llm_conclusion 含"证据不足,无法判定";project.risk_level='indeterminate'

#### Scenario: LLM 重试全失败走降级兜底

- **WHEN** formula_total=72、level=high、有铁证;`call_llm_judge` 重试 `LLM_JUDGE_MAX_RETRY` 次后仍返回 `(None, None)`
- **THEN** final_total=72,final_level=`high`;`llm_conclusion` 以固定前缀 `"AI 综合研判暂不可用"` 开头,包含公式结论模板(total/level/铁证维度/top 维度)

#### Scenario: LLM 输出 bad JSON 走降级兜底

- **WHEN** LLM 返回无法解析的字符串(如缺 `suggested_total` 字段)
- **THEN** 等价 LLM 失败,走降级分支;final_total=formula_total,llm_conclusion=fallback_conclusion 模板

#### Scenario: LLM_JUDGE_ENABLED=false 跳过 LLM

- **WHEN** env `LLM_JUDGE_ENABLED=false`,formula_total=55(medium)
- **THEN** 不调 LLM;final_total=55,final_level=`medium`;llm_conclusion=fallback_conclusion 模板(前缀 "AI 综合研判暂不可用")

#### Scenario: LLM suggested_total 超界走降级

- **WHEN** LLM 返回 `{suggested_total: 120, conclusion: "..."}`(超出 [0,100])
- **THEN** 视为解析失败,走降级分支;final_total=formula_total

#### Scenario: 全 skipped 极端情况仍出报告

- **WHEN** 所有 AgentTask 均 skipped(数据不足),formula_total=0、无铁证
- **THEN** AnalysisReport 生成,final_total=0,final_level=`low`;若 LLM 启用且成功,conclusion 可基于"数据不足"摘要产文;若 LLM 失败,llm_conclusion=fallback_conclusion 模板明示"数据不足"

---

### Requirement: 证据不足判定规则

系统 SHALL 在调用 L-9 LLM 综合研判**之前**先做"证据不足"前置判定。

证据不足的判定函数签名扩 2 个 keyword-only 可选参数(向后兼容):
```
_has_sufficient_evidence(
    agent_tasks,
    pair_comparisons,
    overall_analyses,
    *,
    adjusted_pcs: AdjustedPCs | None = None,
    adjusted_oas: AdjustedOAs | None = None,
) -> bool
```

`adjusted_pcs is None and adjusted_oas is None`(默认,老调用点行为完全不变)时:
1. **铁证短路**:若当前版本的 `PairComparison` 任一 `is_ironclad=True`,或 `OverallAnalysis` 任一 `evidence_json.has_iron_evidence=True` → 直接判定为**有足够证据**(铁证本身就是最强信号),走原 LLM 路径
2. **信号型 agent 判定**:否则过滤 AgentTask 里 `status='succeeded'` 且 `agent_name in SIGNAL_AGENTS` 的任务作为"有效信号"
   - `SIGNAL_AGENTS = {"text_similarity", "section_similarity", "structure_similarity", "image_reuse", "style", "error_consistency"}` — 这些 agent 的 score=0 表示"真的没算出信号"
   - **不在**该集合内的 agent(`metadata_author / metadata_time / metadata_machine / price_consistency`)**不计入**判定分母
3. 若有效信号为空 **或** 全部 `score` 为 0(或 NULL) → 判定为**证据不足**

任一 adjusted dict 非 None 时(本 change 调用点,无 cluster 命中时仍传 None 走老路径):
1. **铁证短路读 adjusted iron**:遍历 PC,iron 状态读 `adjusted_pcs.get(pc.id, {}).get("is_ironclad", pc.is_ironclad)`(若 `adjusted_pcs is None` 则直读 raw);遍历 OA 同理读 `adjusted_oas.get(oa.id, {}).get("has_iron_evidence", oa.evidence_json.get("has_iron_evidence"))`。被 template adjustment 抑制为 false 的不视为铁证
2. **信号判定分母从 AgentTask 切到 OA**:过滤 `oa.dimension in SIGNAL_AGENTS and adjusted_or_raw_score > 0`(`adjusted_or_raw_score = adjusted_oas.get(oa.id, {}).get("score", oa.score)`);AgentTask 仍保留供 agent 执行层面诊断,**不再作为信号判定分母**
3. **前置条件**:调用方 MUST 确保 `overall_analyses` list 已含全部 11 行(4 global + 7 pair 类 DEF-OA)。`judge.py` DEF-OA 写入步骤 `session.add(oa)` + `flush` 后必须 `overall_analyses.append(oa)` 同步 local list;否则 SIGNAL_AGENTS 中 text/section/structure_similarity 的 OA 在分母中缺席,新分母永远 False 误判 indeterminate

**helper 级 kwarg 联动**(具体改造手法见 design D5):`_compute_dims_and_iron` / `_has_sufficient_evidence` / `summarize`(经 `_run_l9` 透传)同步加 `adjusted_pcs / adjusted_oas` kwarg(默认 None 时行为完全不变);`_compute_formula_total` 不扩 kwarg(只读 per_dim_max + has_ironclad);`compute_report` 自身签名/语义不变。

若返 False → 跳过 LLM 调用,直接设 `AnalysisReport.risk_level='indeterminate'` + `llm_conclusion="证据不足,无法判定围标风险(有效信号维度全部为零)"`,`total_score` 按公式照算
若返 True → 进入原 L-9 LLM 调用路径

#### Scenario: 信号型 agent 全零 → 证据不足(老调用点 / adjusted_scores=None)

- **WHEN** 无铁证,11 个 AgentTask 中 3 个 skipped、8 个 succeeded 但信号型 agent 得分全为 0;`adjusted_pcs=None / adjusted_oas=None`
- **THEN** `_has_sufficient_evidence` 返 False;跳过 `call_llm_judge`;AnalysisReport `risk_level='indeterminate'`、`llm_conclusion` 含"证据不足,无法判定"

#### Scenario: 只有 metadata_* 非零信号 → 仍证据不足(老路径)

- **WHEN** 无铁证,`metadata_author.score=50`,但信号型 agent 都是 0 或 skipped;`adjusted_pcs=None / adjusted_oas=None`
- **THEN** `_has_sufficient_evidence` 返 False(metadata_* 不在 SIGNAL_AGENTS 分母里);走 indeterminate 分支

#### Scenario: 铁证短路 → 强制走 LLM 路径(老路径)

- **WHEN** 任一 PC.is_ironclad=True,但所有 AgentTask 的 score=0;`adjusted_pcs=None / adjusted_oas=None`
- **THEN** `_has_sufficient_evidence` 返 True(铁证短路);走原 LLM + 铁证升级路径

#### Scenario: 无 succeeded agent(老路径)

- **WHEN** 所有 AgentTask 都 skipped / failed / timeout,无任何 succeeded,且无铁证;`adjusted_pcs=None / adjusted_oas=None`
- **THEN** `_has_sufficient_evidence` 返 False;同 indeterminate 分支

#### Scenario: 有信号型非零信号照旧走 LLM(老路径)

- **WHEN** 有效信号 agent 至少一个 score > 0;`adjusted_pcs=None / adjusted_oas=None`
- **THEN** `_has_sufficient_evidence` 返 True;正常进入 L-9 LLM 调用

#### Scenario: LLM 失败兜底时仍保持 indeterminate 语义

- **WHEN** 证据不足判定为 False 且 LLM 被跳过,fallback_conclusion 被调
- **THEN** fallback_conclusion 仍按 `risk_level=indeterminate` 处理;`llm_conclusion` 保持"证据不足"语义,不回退到"无围标迹象"文案

#### Scenario: adjusted dict 传入,iron 被抑制 → 铁证短路不命中(新路径)

- **WHEN** `adjusted_pcs` 传入 dict,其中 metadata_author PC 的 is_ironclad 被抑制为 false;原 PC.is_ironclad=true 保留在 DB;无其他真实铁证;`adjusted_oas` 同时传(可只覆盖被剔 OA)
- **THEN** 铁证短路读 `adjusted_pcs[pc.id]["is_ironclad"]=false`,不命中;继续走 OA signal 分母判定

#### Scenario: adjusted dict 传入,OA signal 全零 → indeterminate(新路径)

- **WHEN** adjusted dict 传入,SIGNAL_AGENTS 中所有维度 OA(text_similarity / section_similarity / structure_similarity / image_reuse / style / error_consistency)的调整后 score 全为 0;`overall_analyses` list 长度=11
- **THEN** `_has_sufficient_evidence` 返 False;走 indeterminate 分支

#### Scenario: adjusted dict 传入,text_sim 降权后非零 → 走 LLM(新路径)

- **WHEN** adjusted dict 传入,text_similarity DEF-OA score 调整为 45.5(从 raw 91 降权后),其他 SIGNAL OA=0;无铁证;`overall_analyses` list 长度=11
- **THEN** `_has_sufficient_evidence` 返 True(any 非零);走 LLM 路径;LLM `summarize` 也消费 adjusted dict 输出基于调整后值的 dimensions(防 LLM 拿污染 raw 值后 clamp 拉回污染分);LLM clamp 后最终 risk_level 取决于 LLM 输出(典型 low)

#### Scenario: 真铁证(image_reuse 例外:OA 不写 iron;改用 error_consistency)→ 铁证短路命中

- **WHEN** adjusted dict 传入,error_consistency OA `evidence_json.has_iron_evidence=true` 未被抑制(error_consistency 不在剔除白名单)
- **THEN** 铁证短路命中;返 True 走 LLM + 铁证升级路径;真围标信号在 template 排除下保留有效

#### Scenario: DEF-OA list 长度前置条件失守 → L1 测试断言失败

- **WHEN** 调用方未正确同步 DEF-OA 到 `overall_analyses` local list,调用时 list 长度 < 11
- **THEN** L1 单元测试 MUST 显式断言失败;此前置条件违反不应在生产路径出现

#### Scenario: prod fixture 单 section 信号非零 → 走 LLM(round 4 reviewer M3 边界裁定)

- **WHEN** adjusted dict 传入,reflect prod 真实场景:text_similarity DEF-OA score 调整为 45.80(降权后)/ structure_similarity DEF-OA=0(剔除)/ style OA=0(剔除全覆盖)/ metadata_author / metadata_time DEF-OA=0(剔除)/ section_similarity OA score=70(未受影响,假设 prod 真实分数)/ image_reuse OA=0 / error_consistency OA=0;无铁证(全被抑制 + 无独立 image_reuse/error_consistency 铁证)
- **THEN** `_has_sufficient_evidence` 返 True(text_sim DEF-OA 与 section_sim 各自非零,任一即足);走 LLM 路径;LLM `summarize` 消费 adjusted dict 输出 dimensions(structure/style/metadata_author 全 0);final_total 由 LLM clamp + adjusted has_ironclad=False 决定,典型落 low

---

### Requirement: AnalysisReport risk_level 新增 indeterminate 枚举值

`analysis_reports.risk_level` 字段枚举值 MUST 扩展为 4 类:`high / medium / low / indeterminate`。DB 层面字段类型保持 `String(16)` 无变更(当前无 CheckConstraint),仅需在 Pydantic Literal、前端 TypeScript Union、Word 模板、所有按 `risk_level` 分支的渲染点加 `indeterminate` case。

- `indeterminate` 语义:"证据不足,无法判定围标风险"(对应"证据不足判定规则"Requirement 的输出)
- Pydantic schema `AnalysisReportResponse.risk_level: Literal["high", "medium", "low", "indeterminate"]`
- `project.risk_level`(projects 表 cached 字段)同步支持 indeterminate
- 前端 `types/index.ts` 的 `RiskLevel` 和 `ProjectRiskLevel` union 加 `"indeterminate"` 成员
- 历史 high/medium/low 数据 MUST 零影响(纯前向兼容扩展)

#### Scenario: Pydantic schema 验证 indeterminate

- **WHEN** 构造 `AnalysisReportResponse(risk_level="indeterminate", ...)` 
- **THEN** 验证通过,序列化为 JSON 字段值为 `"indeterminate"`

#### Scenario: 历史 low 数据不受影响

- **WHEN** 读取 change 实施前创建的 AnalysisReport(risk_level="low")
- **THEN** Pydantic 反序列化成功,前端正常渲染为绿色"低风险"标签

#### Scenario: Word 导出支持 indeterminate

- **WHEN** 导出 `risk_level=indeterminate` 的报告为 Word
- **THEN** 模板选择对应文案串(不写"低风险",写"证据不足");文档能正常生成

---

### Requirement: global 类 agent early-return 分支 MUST 写 OA 行

error_consistency 和 image_reuse agent 在 early-return 分支(session=None 或 bidders<2 等数据不足场景)MUST 写入 OA 行(score=0, evidence_json 含 skip_reason),与 style agent 现有行为对齐。

所有 4 个 global agent(error_consistency / image_reuse / price_anomaly / style)在任何执行路径(正常/skip/early-return)下 MUST 保证写入恰好一行 OA。

#### Scenario: error_consistency 数据不足仍写 OA

- **WHEN** error_consistency agent 因 bidders < 2 而 skip
- **THEN** overall_analyses 仍有 error_consistency 行:score=0, evidence_json 含 `skip_reason`

#### Scenario: image_reuse session=None 仍写 OA

- **WHEN** image_reuse agent 在无 session 环境运行(如 L1 测试)
- **THEN** 不写 OA(session=None 静默跳过,与 write_overall_analysis_row 现有契约一致)

#### Scenario: image_reuse 有 session 但数据不足

- **WHEN** image_reuse agent 有 session 但无图片数据
- **THEN** overall_analyses 有 image_reuse 行:score=0, evidence_json 含 `skip_reason`

---

### Requirement: AnalysisReport 与 PairComparison / OverallAnalysis 数据模型

表结构 MUST 满足:

**`pair_comparisons`**:
- `id / project_id FK / version INTEGER / bidder_a_id FK / bidder_b_id FK / dimension VARCHAR(64) / score NUMERIC(6,2) / evidence_json JSONB / is_ironclad BOOLEAN NOT NULL DEFAULT false / created_at`
- 索引 `(project_id, version, dimension)`

**`overall_analyses`**:
- `id / project_id FK / version INTEGER / dimension VARCHAR(64) / score NUMERIC(6,2) / evidence_json JSONB / created_at`
- 索引 `(project_id, version, dimension)`

**`analysis_reports`**:
- `id / project_id FK / version INTEGER / total_score NUMERIC(6,2) / risk_level VARCHAR(16) / llm_conclusion TEXT NOT NULL DEFAULT '' / created_at`
- UNIQUE `(project_id, version)` — 一轮检测一条报告

`evidence_json` 字段 SQLite 退化为 JSON/TEXT,PostgreSQL 用 JSONB。

#### Scenario: 三表同时建立

- **WHEN** `alembic upgrade head`
- **THEN** 3 张表存在;UNIQUE 和索引按 spec 建立

#### Scenario: AnalysisReport UNIQUE 约束

- **WHEN** 尝试 INSERT 同 project_id + version 的第二条 AnalysisReport
- **THEN** 数据库抛 IntegrityError;测试捕获

---

### Requirement: 检测状态快照 API

系统 SHALL 提供 `GET /api/projects/{pid}/analysis/status` 端点,返回项目当前 version(或最近一次失败版本)的 AgentTask 级快照。权限同项目详情(reviewer 仅自己/admin 任意)。

响应:
```json
{
  "version": int | null,
  "project_status": "draft|parsing|ready|analyzing|completed",
  "started_at": iso8601 | null,
  "report_ready": bool,
  "agent_tasks": [
    {"id", "agent_name", "agent_type", "pair_bidder_a_id", "pair_bidder_b_id",
     "status", "started_at", "finished_at", "elapsed_ms", "score", "summary", "error"}
  ]
}
```

- **[新增] `report_ready`**(honest-detection-results):当且仅当 `(project_id, version)` 在 `analysis_reports` 表有对应行时返 True;用于客户端区分 "agent 终态但 judge 未完成"(`report_ready=false`)vs "完全完成"(`report_ready=true`)。
- `version=null` 的响应中 `report_ready` 固定为 `false`。
- 项目从未启动检测(无 AgentTask)→ 返 `{"version": null, "project_status": <current>, "report_ready": false, "agent_tasks": []}` 200(非 404,便于前端幂等拉取)。

#### Scenario: 检测中查看快照

- **WHEN** 检测进行中 → `GET /api/projects/{pid}/analysis/status`
- **THEN** 响应 200,`agent_tasks` 列表含所有条目,status 混合 `running / pending / succeeded`,`report_ready=false`

#### Scenario: agent 全终态但 judge 未完成

- **WHEN** 所有 AgentTask 进终态但 `analysis_reports` 该 version 行尚未 INSERT
- **THEN** 响应 `report_ready=false`,提示客户端继续轮询

#### Scenario: 检测完全完成

- **WHEN** `analysis_reports` 该 version 行已写入
- **THEN** 响应 `report_ready=true`;客户端可安全拉取 `/reports/{version}`

#### Scenario: report_ready 与 project_status 短暂不一致时以 report_ready 为权威

- **WHEN** judge_and_create_report 已 INSERT AnalysisReport 行但尚未 UPDATE `project.status='completed'`(两步之间 ~几十毫秒窗口)
- **THEN** `/analysis/status` 响应可能出现 `report_ready=true` + `project_status='analyzing'` 组合;前端 MUST 以 `report_ready` 为拉报告的权威判据,不看 project_status(后者下一次轮询会一致)

#### Scenario: 从未检测过返空

- **WHEN** 新建项目(无 AgentTask)→ 查询
- **THEN** 响应 200 + `{"version": null, "project_status": "draft", "report_ready": false, "agent_tasks": []}`

#### Scenario: 非 owner 返 404

- **WHEN** reviewer A 查询 B 的项目 analysis/status
- **THEN** 响应 404

---

### Requirement: SSE 检测事件流

系统 SHALL 提供 `GET /api/projects/{pid}/analysis/events`,以 `text/event-stream` 响应推送检测相关事件。权限同项目详情。

**首帧**:当前 version 所有 AgentTask 快照(payload 同 "检测状态快照 API")。
**后续事件**:
- `agent_status`:单个 Agent 状态变更(payload 见 design.md D5)
- `report_ready`:AnalysisReport 生成(payload 见 design.md D5)
- `heartbeat`:每 15s 一个心跳(保持连接)

响应头 MUST 含 `Cache-Control: no-cache`、`X-Accel-Buffering: no`(防止 nginx 缓冲)。

客户端断开 → server 端 unsubscribe broker queue,释放资源。

#### Scenario: 连接建立收到首帧

- **WHEN** 客户端 `curl -N /api/projects/{pid}/analysis/events`
- **THEN** 200 + content-type text/event-stream;第一个 SSE frame 为 `event: snapshot\ndata: {...}`

#### Scenario: Agent 完成推送事件

- **WHEN** text_similarity Agent 完成
- **THEN** SSE 流中出现 `event: agent_status\ndata: {"agent_name": "text_similarity", "status": "succeeded", ...}`

#### Scenario: 所有 Agent 完成推送 report_ready

- **WHEN** 最后一个 AgentTask 完成 → judge 生成 AnalysisReport
- **THEN** SSE 流中出现 `event: report_ready\ndata: {"version": N, "total_score": X, ...}`

#### Scenario: 非 owner 403/404

- **WHEN** reviewer A 订阅 B 的项目 events
- **THEN** 响应 404

---

### Requirement: 报告骨架 API

系统 SHALL 提供 `GET /api/projects/{pid}/reports/{version}` 端点,返回指定 version 的报告骨架数据。权限同项目详情。

响应:
```json
{
  "version": int,
  "total_score": float,
  "risk_level": "high|medium|low",
  "llm_conclusion": string,  // C6 恒为空字符串
  "created_at": iso8601,
  "dimensions": [
    {"dimension": "text_similarity", "best_score": float, "is_ironclad": bool,
     "status_counts": {"succeeded": int, "failed": int, "timeout": int, "skipped": int},
     "summaries": [string, ...]}  // 该维度下所有 AgentTask 的 summary 列表
  ]  // 10 个维度,按 is_ironclad desc + best_score desc 排序
}
```

报告不存在 → 404。详细 Tab(对比详情 / 雷达图 / 热力图 / 检测日志)留 **C14** 实施,C6 不提供。

#### Scenario: 报告存在返骨架

- **WHEN** `GET /api/projects/{pid}/reports/1` 且 AnalysisReport 存在
- **THEN** 响应 200 + 上述 JSON 结构;dimensions 数组长度 10

#### Scenario: 报告不存在返 404

- **WHEN** 请求 `version=99` 但 AnalysisReport 无此行
- **THEN** 响应 404

#### Scenario: 铁证命中 is_ironclad 字段为 true

- **WHEN** 某维度存在 pair_comparisons.is_ironclad=true
- **THEN** 响应中该 dimension 的 is_ironclad=true;排序置顶

---

### Requirement: async_tasks 通用任务表与重启恢复

系统 MUST 提供 `async_tasks` 表追踪 4 类异步任务(subtype ∈ `extract / content_parse / llm_classify / agent_run`),字段见 proposal.md / design.md D1。

表字段:`id / subtype VARCHAR(32) / entity_type VARCHAR(32) / entity_id INTEGER / status VARCHAR(16) / started_at / heartbeat_at / finished_at / error TEXT / created_at`;索引 `(status, heartbeat_at)`。

系统 MUST 提供上下文管理器 `async with track(subtype, entity_type, entity_id):`:
1. 进入:INSERT 一行 `{status='running', heartbeat_at=now()}`;启后台协程每 30s UPDATE heartbeat_at = now()
2. 退出(无异常):UPDATE status='done', finished_at=now();取消心跳协程
3. 退出(异常):UPDATE status='failed', error=str(exc)[:500];取消心跳协程;**重新抛出异常**

系统 MUST 在后端启动时(FastAPI lifespan startup)调 `scanner.scan_and_recover()`:
1. 查 `async_tasks WHERE status='running' AND heartbeat_at < now() - 60 seconds`
2. 每行按 subtype 分派回滚 handler(见 design.md D1 表):
   - `extract`:bidder.parse_status: `extracting → failed` + parse_error="系统重启导致解压任务中断,请重试"
   - `content_parse`:bid_document.parse_status: `identifying → identify_failed`;`_aggregate_bidder_status(bidder_id)`
   - `llm_classify`:bidder.parse_status: `identifying → identify_failed`
   - `agent_run`:agent_tasks.status: `running → timeout`;若该 project 所有 AgentTask 均 terminate → project.status `analyzing → ready`
3. 标 async_tasks.status = `timeout`
4. 单 handler 失败不影响其他(独立 try)

已有调用点:
- C4 `extract/engine.py` MUST 用 `async with track(subtype='extract', entity_type='bidder', entity_id=bidder.id):` 包裹解压协程
- C5 `parser/content/__init__.py` MUST 用 `async with track(subtype='content_parse', entity_type='bid_document', entity_id=doc.id):` 包裹 extract_content
- C5 `parser/llm/role_classifier.py` MUST 用 `async with track(subtype='llm_classify', entity_type='bidder', entity_id=bidder.id):` 包裹 classify_bidder
- C6 engine MUST 用 `async with track(subtype='agent_run', entity_type='agent_task', entity_id=task.id):` 包裹单 Agent 执行

#### Scenario: scanner 启动扫空表 no-op

- **WHEN** 干净数据库后端启动
- **THEN** scanner 扫 async_tasks 表为空,no-op;日志输出 "scanner: 0 stuck tasks"

#### Scenario: extract 阶段 stuck 恢复

- **WHEN** async_tasks 有 1 行 `subtype=extract, entity_id=5, heartbeat_at=now()-120s`;对应 bidder 5 `parse_status='extracting'`
- **THEN** 后端启动后 scanner 扫到该行 → UPDATE bidder 5 parse_status='failed' + parse_error 含 "系统重启";UPDATE async_tasks status='timeout';日志输出 "scanner: 1 extract recovered"

#### Scenario: agent_run 恢复触发 project.status 回滚

- **WHEN** 项目 P1 `status='analyzing'`,所有 AgentTask 均为 running 且心跳过期
- **THEN** scanner 扫后所有 AgentTask status='timeout';P1 status 回 'ready'

#### Scenario: 单 handler 失败不影响其他

- **WHEN** 2 行 stuck,第 1 行 handler 抛异常
- **THEN** 第 2 行仍被正确处理;异常第 1 行标 status='failed' + error 记录

#### Scenario: track 异常重抛

- **WHEN** `async with track(...): raise ValueError("boom")`
- **THEN** 退出时 async_tasks.status='failed',error='ValueError: boom';外层仍捕获到 ValueError

---

### Requirement: 10 Agent 骨架文件与 dummy run

后端 MUST 在 `app/services/detect/agents/` 下提供 **11** 个 Agent 骨架文件(原 10 + C12 新增 `price_anomaly.py`),每个文件定义一个 Agent 骨架,通过 `@register_agent` 装饰器注册到 AGENT_REGISTRY。

C13 归档后,**全部 11 个 Agent 的 `run()` 均为真实算法,dummy 列表清空**。已替换 Agent:
- pair 型(C7~C11):`text_similarity` / `section_similarity` / `structure_similarity` / `metadata_author` / `metadata_time` / `metadata_machine` / `price_consistency`
- global 型:`price_anomaly`(C12 新增,直接带真实 run)/ `error_consistency`(C13)/ `image_reuse`(C13)/ `style`(C13)

每个骨架文件 MUST 含:
- `preflight` 函数(按 "Agent preflight 前置条件自检" Requirement 规则)
- `run(ctx: AgentContext) -> AgentRunResult` 函数,调用各自子包(`text_sim_impl / section_sim_impl / structure_sim_impl / metadata_impl / price_impl / anomaly_impl / error_impl / image_impl / style_impl`)的真实算法

`AgentRunResult` 是 namedtuple,字段:`score: float, summary: str, evidence_json: dict = {}`(3 字段,不扩展)。当整 Agent 因数据缺失 run 级 skip 时 `score=0.0` 作为哨兵值,evidence 层通过 `participating_fields=[]`(或 `participating_dimensions=[]` / `participating_subdims=[]`,按 Agent 定义)标记。

**铁证传递契约**(C13 现场确认):
- **pair 型 Agent**:run() 内部调 `write_pair_comparison_row(..., is_ironclad=True)` → `PairComparison.is_ironclad` 字段 → judge.py 从 DB 读
- **global 型 Agent**:run() 内部写 evidence_json 顶层 `has_iron_evidence: bool` → `OverallAnalysis.evidence_json["has_iron_evidence"]` → judge.py 从 DB 读(C13 扩 judge.compute_report 支持)

**注意**:C13 归档后,dummy 列表为空。后续如有新 Agent 加入(如 C14 LLM 综合研判 judge 升级,如需新 Agent),需独立 change 替换。

#### Scenario: 11 Agent 模块加载后注册表完整

- **WHEN** `from app.services.detect import agents` 触发所有 agents 模块加载
- **THEN** `AGENT_REGISTRY` 含 11 条目;每条 `run` 可调

#### Scenario: text_similarity 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["text_similarity"].run(ctx)` 且段落对存在
- **THEN** `evidence_json["algorithm"] == "tfidf_cosine_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: section_similarity 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["section_similarity"].run(ctx)` 且章节切分成功
- **THEN** `evidence_json["algorithm"] == "tfidf_cosine_chapter_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: structure_similarity 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["structure_similarity"].run(ctx)` 且至少一个维度可提取
- **THEN** `evidence_json["algorithm"] == "structure_sim_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: metadata_author 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["metadata_author"].run(ctx)` 且元数据足够
- **THEN** `evidence_json["algorithm"] == "metadata_author_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: metadata_time 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["metadata_time"].run(ctx)` 且元数据时间字段足够
- **THEN** `evidence_json["algorithm"] == "metadata_time_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: metadata_machine 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["metadata_machine"].run(ctx)` 且元数据机器指纹字段足够
- **THEN** `evidence_json["algorithm"] == "metadata_machine_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: price_consistency 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["price_consistency"].run(ctx)` 且双方 PriceItem 存在
- **THEN** `evidence_json["algorithm"] == "price_consistency_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: price_anomaly 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["price_anomaly"].run(ctx)` 且项目下 ≥ 3 家 bidder 已成功解析报价
- **THEN** `evidence_json["algorithm"] == "price_anomaly_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: error_consistency 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["error_consistency"].run(ctx)` 且至少一对 bidder identity_info 非空
- **THEN** `evidence_json["algorithm_version"] == "error_consistency_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: image_reuse 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["image_reuse"].run(ctx)` 且至少 2 个 bidder 有图片
- **THEN** `evidence_json["algorithm_version"] == "image_reuse_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: style 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["style"].run(ctx)` 且至少 2 个 bidder 有 technical 角色文档
- **THEN** `evidence_json["algorithm_version"] == "style_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

### Requirement: text_similarity 双轨算法(本地 TF-IDF + LLM 定性)

Agent `text_similarity` 的 `run()` MUST 采用双轨分工:

1. **本地 TF-IDF 筛选**(始终执行):
   - 取双方同角色文档的段落列表(优先 `技术方案`,无则回退 `商务`、`其他`)
   - jieba 分词 + 去停用词 + `TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_df=0.95, max_features=20000)`
   - `cosine_similarity(mat_a, mat_b)` 构造段落对相似度矩阵
   - 取 `sim >= TEXT_SIM_PAIR_SCORE_THRESHOLD`(默认 0.70)的段落对,按 sim 降序截取前 `TEXT_SIM_MAX_PAIRS_TO_LLM`(默认 30)条
2. **LLM 定性判定**(超阈值段落对存在时执行):
   - 按 requirements.md §10.8 L-4 规格组 prompt:输入双方名称、文档角色、段落对列表(含文本和程序相似度)
   - 请求 LLM 返回 JSON:每对段落 `judgment ∈ {template, generic, plagiarism}` + 整体 `overall` + `confidence ∈ {high, medium, low}`
   - 严格 JSON 解析;失败 → 重试 1 次;仍失败 → 降级
3. **score 汇总**:每对 `score_i = sim * 100 * W[judgment]`,其中 `W = {plagiarism: 1.0, template: 0.6, generic: 0.2, None(降级): 0.3}`;pair 级 `score = round(max(scored) * 0.7 + mean(scored) * 0.3, 2)`
4. **is_ironclad 判定**:LLM 非降级模式下,若 `plagiarism` 对数 ≥ 3 或占比 ≥ 50% → `is_ironclad = True`;降级模式下始终 `False`

CPU 密集步骤(TF-IDF 向量化 + cosine 计算)MUST 走 `get_cpu_executor()` + `loop.run_in_executor()`,不阻塞 event loop。

#### Scenario: 抄袭样本高分命中

- **WHEN** pair(A, B)双方技术方案段落包含 ≥ 5 段几乎逐字相同的文本,LLM 返回全部 plagiarism
- **THEN** PairComparison.score ≥ 85.0,is_ironclad = True,evidence_json.pairs_plagiarism ≥ 5

#### Scenario: 独立样本低分不误报

- **WHEN** pair(A, B)双方文档独立撰写,TF-IDF 筛选无段落对 sim ≥ 0.70
- **THEN** PairComparison.score < 20.0,is_ironclad = False,evidence_json.pairs_total = 0,LLM 未被调用

#### Scenario: 三份中一对命中

- **WHEN** 3 家 bidder 中仅 (A, B) 对抄袭,(A, C) 和 (B, C) 独立
- **THEN** pair(A,B).score 高 + is_ironclad=True;pair(A,C) / (B,C) score 低 + is_ironclad=False

#### Scenario: 段落对 sim 超阈值但 LLM 判为 generic

- **WHEN** LLM 返回全部段落对 judgment = generic(行业通用表述)
- **THEN** PairComparison.score 按 generic 权重 0.2 折算;is_ironclad = False

---

### Requirement: text_similarity preflight 超短文档 skip

Agent `text_similarity` preflight MUST 在"同角色文档存在"基础上追加字数检查:
- 任一 bidder 的待比对文档总字符数 < `TEXT_SIM_MIN_DOC_CHARS`(默认 500)→ 返 `PreflightResult(status='skip', reason='文档过短无法对比')`
- 双方均满足 `>= TEXT_SIM_MIN_DOC_CHARS` → 返 `ok`

此扩展 MUST 保持 C6 定义的 `PreflightResult(status='skip' | 'ok')` 接口不变;不新增 `downgrade` 分支。

#### Scenario: 单边超短文档 preflight skip

- **WHEN** bidder_a 技术方案总字符 300(< 500),bidder_b 2000
- **THEN** 返 `PreflightResult(status='skip', reason='文档过短无法对比')`

#### Scenario: 双方足够字数 preflight ok

- **WHEN** 双方技术方案总字符均 ≥ 500
- **THEN** 返 `PreflightResult(status='ok')`

#### Scenario: 原"同角色文档存在"规则保留

- **WHEN** bidder_a 有技术方案,bidder_b 无技术方案
- **THEN** 返 `PreflightResult(status='skip', reason='缺少可对比文档')`(字数检查不触发,因无可比对文档)

---

### Requirement: text_similarity LLM 降级模式

当 LLM 调用失败(`LLMResult.error` 非空,kind ∈ timeout / rate_limit / network / other)或 JSON 解析两次(初 + 1 重试)都失败,Agent `text_similarity` MUST 进入降级模式:

1. 不再调用 LLM;本地 TF-IDF 筛选结果仍保留
2. `evidence_json.degraded = true`,`evidence_json.ai_judgment = null`
3. `score` 按所有段落对 `judgment = None` 权重 0.3 计算(D4 公式)
4. `is_ironclad = False`(降级永远不触发铁证)
5. `summary` 固定文案 "AI 研判暂不可用,仅展示程序相似度(降级)"
6. AgentTask `status = succeeded`(降级不是失败,程序相似度仍可用)

#### Scenario: LLM 超时降级

- **WHEN** `ctx.llm_provider.complete()` 返 `LLMResult(error=LLMError(kind='timeout'))`
- **THEN** evidence_json.degraded = True,AgentTask.status = succeeded,summary 含 "降级"

#### Scenario: LLM 返回非 JSON 降级

- **WHEN** LLM 返回 plain text 非 JSON,初次解析失败;重试仍返 plain text
- **THEN** evidence_json.degraded = True,score 按权重 0.3 保守计算

#### Scenario: LLM 返回 JSON 但段数不匹配

- **WHEN** 输入 10 段落对,LLM 只返回 7 段的 judgment
- **THEN** 缺失 3 段按 judgment='generic' 补齐;不触发降级(不算错误)

---

### Requirement: text_similarity evidence_json 结构

`PairComparison.evidence_json` 对 `dimension = 'text_similarity'` 的行 MUST 包含以下字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| `algorithm` | string | 固定 `"tfidf_cosine_v1"`,区分 dummy |
| `doc_role` | string | 实际比对的文档角色 |
| `doc_id_a` / `doc_id_b` | int | 被比对的 BidDocument id |
| `threshold` | float | 本次 TEXT_SIM_PAIR_SCORE_THRESHOLD 实际值 |
| `pairs_total` | int | 超阈值段落对总数 |
| `pairs_plagiarism` | int | LLM 判 plagiarism 段数(降级模式 = 0) |
| `pairs_template` | int | LLM 判 template 段数(降级模式 = 0) |
| `pairs_generic` | int | LLM 判 generic 段数(降级模式 = pairs_total) |
| `degraded` | bool | LLM 是否降级 |
| `ai_judgment` | object/null | `{overall: string, confidence: string}`,降级时 null |
| `samples` | array | 按 sim 降序前 10 条 `{a_idx, b_idx, a_text, b_text, sim, label, note}` |

`samples` 上限 10 条以控制 JSONB 大小;`a_text` / `b_text` 每条最多截取 200 字符。

#### Scenario: 正常 evidence_json 结构

- **WHEN** text_similarity 正常完成(LLM 成功)
- **THEN** evidence_json 含 algorithm="tfidf_cosine_v1" + ai_judgment 非 null + samples ≤ 10

#### Scenario: 降级 evidence_json 结构

- **WHEN** text_similarity LLM 降级完成
- **THEN** evidence_json.degraded=true + ai_judgment=null + samples 仍有(程序相似度保留)

---

### Requirement: text_similarity ProcessPoolExecutor 消费

Agent `text_similarity.run()` MUST 通过 `loop.run_in_executor(get_cpu_executor(), compute_pair_similarity, paras_a, paras_b, threshold)` 将 TF-IDF 向量化 + cosine 矩阵计算卸载到 ProcessPoolExecutor,主协程不阻塞。

`compute_pair_similarity` MUST 是无副作用的纯函数(入参 `list[str] × list[str] × float`,出参 `list[ParaPair]`),可序列化,可在子进程独立跑完。

`TfidfVectorizer` 实例在子进程内 new,不跨进程传递。

#### Scenario: executor 被调用

- **WHEN** text_similarity run 执行 CPU 密集段
- **THEN** `get_cpu_executor()` 返回的 ProcessPoolExecutor 被消费(L1 通过 spy 验证;L2 真实运行)

#### Scenario: jieba 首次调用不崩溃

- **WHEN** 后端启动后首个 text_similarity task(worker 子进程首次 import jieba)
- **THEN** Agent 成功完成;elapsed_ms 可能 > 1000ms(首次词典加载) 但 status=succeeded

---

### Requirement: 测试基础设施扩展

后端测试 fixtures MUST 扩展以支持 C6:

1. `clean_users` fixture 按 FK 依赖顺序新增 5 张表清理(前置于 projects):`async_tasks → analysis_reports → overall_analyses → pair_comparisons → agent_tasks`
2. 环境变量 `INFRA_DISABLE_DETECT=1` MUST 被 engine 读取:为 1 时 `POST /analysis/start` 仅创建 AgentTask 行 + UPDATE project.status,但不 `asyncio.create_task(run_detection)`(L2 测试手动调 run_detection 验证)
3. `llm_mock.py` fixture 扩展(C6 不调 LLM,但预留 `mock_llm_judge_success` 给 C14 使用)

#### Scenario: clean_users 扩 5 表

- **WHEN** 任一 L2 测试开始前
- **THEN** 5 张 C6 表 + 4 张 C5 表 + 4 张 C4 表 + projects + users 全部清空

#### Scenario: INFRA_DISABLE_DETECT 跳过自动调度

- **WHEN** `INFRA_DISABLE_DETECT=1` 下 POST analysis/start
- **THEN** AgentTask 行创建但所有 status 恒为 `pending`(未执行);project.status='analyzing';测试可手动调 run_detection

---

### Requirement: ProcessPoolExecutor 接口预留

系统 MUST 在 `app/services/detect/engine.py` 提供 `get_cpu_executor() -> ProcessPoolExecutor` lazy 单例;maxworkers = `os.cpu_count() or 2`。

C6 dummy Agent 不消费此 executor;C7~C13 真实 CPU 密集 Agent 实施时调 `await loop.run_in_executor(get_cpu_executor(), fn, *args)`。

后端关闭时(FastAPI lifespan shutdown)MUST 调 `executor.shutdown(wait=False, cancel_futures=True)` 释放资源。

#### Scenario: 接口存在且 lazy

- **WHEN** 应用启动后未调任何 Agent
- **THEN** `_CPU_EXECUTOR` 为 None;首次调 `get_cpu_executor()` 时才初始化

#### Scenario: 关闭释放资源

- **WHEN** FastAPI shutdown
- **THEN** 若已初始化 executor → shutdown 被调用;无异常

---

### Requirement: 前端启动检测按钮与进度指示

前端 MUST 在 `ProjectDetailPage` 集成 `StartDetectButton` + `DetectProgressIndicator`:

`StartDetectButton`:
- bidder < 2 或有非终态 bidder → 按钮禁用 + hover 提示对应文案
- 项目 analyzing → 按钮替换为 "检测进行中" 禁用状态
- 点击 → 调 `POST /analysis/start` → 成功刷新进度
- 401/404/400 错 → Toast 红色提示;409 → 提示"检测已在进行"并跳转进度面板

`DetectProgressIndicator`:
- 订阅 `/analysis/events` SSE
- 进度条:`N/10 维度完成`(completed + skipped + failed + timeout) / 10
- 一行最新动态:最近一个 `agent_status` 事件的 `"<agent_name> <status> <summary>"`
- 全部终态 → 显示 "查看报告" 按钮(跳转 `/reports/:projectId/:version`)

#### Scenario: bidder 数不足按钮禁用

- **WHEN** 项目仅 1 bidder → 打开 ProjectDetailPage
- **THEN** StartDetectButton 禁用,hover tooltip = "至少需要2个投标人"

#### Scenario: SSE 推进度条更新

- **WHEN** SSE 收到 3 个 agent_status 事件(2 succeeded + 1 skipped)
- **THEN** 进度条显示 "3/10",一行摘要显示最近完成的 Agent

#### Scenario: SSE 断线降级轮询

- **WHEN** EventSource onerror 触发
- **THEN** useDetectProgress hook 启 3s 轮询 `/analysis/status`;onmessage 恢复后清 interval

#### Scenario: 全部完成跳转报告

- **WHEN** 10 个 AgentTask 全部终态 + report_ready 事件到达
- **THEN** UI 显示 "查看报告" 按钮;点击 → 路由跳转 `/reports/:projectId/:version`

---

### Requirement: 前端报告页 Tab1 骨架

前端 MUST 提供 `/reports/:projectId/:version` 路由 + `ReportPage` 组件,C6 内仅实现 Tab1 总览骨架:

- 顶栏:风险等级徽章(高红/中橙/低绿)+ 总分;version 选择器(仅 version > 1 时显示)
- 10 维度得分列表:按 `is_ironclad desc` + `best_score desc` 排序;每行显示维度名 / 最高分 / 状态计数汇总 / summary
- LLM 结论区:占位卡片 "AI 综合研判暂不可用 — 将在后续版本支持"
- 不做:雷达图 / 热力图 / Markdown / Tab 切换 / 证据详情抽屉(**全部留 C14**)

报告 API 404 → 页面显示 "报告不存在或正在生成" 回退。

#### Scenario: 报告页渲染基础内容

- **WHEN** 访问 `/reports/:pid/:version` 且 API 返骨架数据
- **THEN** 页面展示风险等级徽章 + 10 维度列表 + LLM 占位卡片

#### Scenario: 高风险红色徽章

- **WHEN** 返回 risk_level='high'
- **THEN** 徽章颜色为红色(CSS 类 `bg-red-*`)

#### Scenario: 铁证维度排序置顶

- **WHEN** dimension 数组中 text_similarity `is_ironclad=true`
- **THEN** UI 中该行排第一,样式加粗/红色标记

---

### Requirement: section_similarity 章节级双轨算法

Agent `section_similarity` 的 `run()` MUST 采用章节级双轨分工,分 5 步:

1. **段落加载**:复用 C7 `text_sim_impl.segmenter.choose_shared_role` + `load_paragraphs_for_roles`,选两侧共有 file_role(按 `ROLE_PRIORITY`)的 BidDocument,加载 body 段落
2. **正则切章**:按 5 种 PATTERN(`第X章 / 第X节 / X.Y 数字序号 / 一、二、 中文数字 / 纯数字+顿号`)识别标题行,切出 `list[ChapterBlock]`;章节内文本 < `SECTION_SIM_MIN_CHAPTER_CHARS`(默认 100)的合并进前一章节
3. **切分成功性判定**:若任一侧 `len(chapters) < SECTION_SIM_MIN_CHAPTERS`(默认 3)或两侧总段落数 < 10 → 触发降级分支(见 "section_similarity 降级模式" Requirement)
4. **章节对齐**:按 title TF-IDF sim 贪心配对(复用 `text_sim_impl.tfidf.jieba_tokenizer`),sim ≥ `SECTION_SIM_TITLE_ALIGN_THRESHOLD`(默认 0.40)标 `aligned_by='title'`;未达阈值的未配对章节按 `idx` 序号对齐,标 `aligned_by='index'`;配对数 = `min(|chapters_a|, |chapters_b|)`
5. **章节级评分 + pair 级汇总**:对每对章节,复用 C7 `text_sim_impl.tfidf.compute_pair_similarity` 算段落对相似度,然后将所有对齐章节的段落对合并按 `title_sim × avg_para_sim` 粗排后取前 `TEXT_SIM_MAX_PAIRS_TO_LLM`(复用 C7 的 30)送 LLM,复用 `text_sim_impl.llm_judge` + `text_sim_impl.aggregator`;pair 级 score = `max(chapter_scores) * 0.6 + mean(chapter_scores) * 0.4`;pair 级 is_ironclad = `any(chapter.is_chapter_ironclad)`

CPU 密集步骤(段落 TF-IDF + title TF-IDF)MUST 走 `get_cpu_executor()`(与 C7 共享 ProcessPoolExecutor)。

#### Scenario: 章节雷同命中

- **WHEN** pair(A, B)双方技术方案章节存在 ≥ 2 章节逐字相同
- **THEN** PairComparison.score ≥ 60.0,is_ironclad = True,evidence_json.algorithm = "tfidf_cosine_chapter_v1",evidence_json.chapter_pairs 含 ≥ 2 个 is_chapter_ironclad=True 的章节对

#### Scenario: 章节错位对齐

- **WHEN** bidder_a 的"技术方案"在 idx=2,bidder_b 的"技术方案"在 idx=3(整体章节数不同但同主题章节标题相近)
- **THEN** aligner 将 (a_idx=2, b_idx=3) 配对,`aligned_by='title'`,title_sim ≥ 0.40

#### Scenario: 无对齐命中走序号回退

- **WHEN** 双方所有章节标题 TF-IDF 均 < 0.40(如纯数字标题)
- **THEN** 每章节按 idx 回退对齐,`aligned_by='index'`,title_sim 可能为 0 但 chapter_score 仍计算

#### Scenario: 单侧多余章节被丢

- **WHEN** bidder_a 含 10 章节,bidder_b 含 6 章节
- **THEN** 对齐后 chapter_pairs 数 = 6,a 的多余 4 章节不参与比较

---

### Requirement: section_similarity preflight

Agent `section_similarity` preflight MUST 执行:
1. 双方均有同 file_role 的 BidDocument(复用 `segmenter.choose_shared_role`)
2. 双方选中文档总字符数 ≥ `TEXT_SIM_MIN_DOC_CHARS`(复用 C7 env,默认 500)

**章节数检查不在 preflight 阶段做**(需提前执行完整切章,成本高),下放到 `run()` 内部;切章失败走降级路径,不返回 `skip`。

#### Scenario: 同角色文档缺失 skip

- **WHEN** 任一侧无同 file_role 的 BidDocument
- **THEN** 返 `PreflightResult(status='skip', reason='缺少可对比文档')`

#### Scenario: 文档过短 skip

- **WHEN** 任一侧选中文档 total_chars < 500
- **THEN** 返 `PreflightResult(status='skip', reason='文档过短无法对比')`

#### Scenario: 章节数少不算 skip

- **WHEN** 双方文档均 ≥ 500 字但切章后 chapter_a=1 < MIN_CHAPTERS=3
- **THEN** preflight 仍返 `ok`;run 内部切章发现章节不足后走降级,不返回 skip

---

### Requirement: section_similarity 降级模式(章节切分失败)

当章节切分失败(任一侧 `len(chapters) < SECTION_SIM_MIN_CHAPTERS`,或双方总段落数 < 10),Agent `section_similarity` MUST 降级到整文档粒度:

1. **不再切章**,直接复用 C7 `text_sim_impl.tfidf.compute_pair_similarity` 对双方整文档段落计算 sim
2. **调 LLM 定性**(复用 C7 `text_sim_impl.llm_judge`);LLM 也失败时走 C7 既有降级(`evidence.degraded=true` 并存 `evidence.degraded_to_doc_level=true`)
3. **写 dimension='section_similarity'**(**不是 text_similarity**),与 C7 并行独立;两维度在 judge.py 按各自权重计入总分,不去重
4. **`evidence_json.algorithm = "tfidf_cosine_fallback_to_doc"`**(区别于 chapter_v1)
5. **`evidence_json.degraded_to_doc_level = true` + `evidence_json.degrade_reason` 填具体原因**(如 "章节切分失败(chapters_a=0, chapters_b=2, < 3)")
6. **AgentTask.status = 'succeeded'**(降级不是失败)
7. **is_ironclad 判定同 C7**(`plagiarism_count >= 3` 或 `>= 50%`)— 章节级证据不存在故不启用章节铁证规则

#### Scenario: 双方章节数都为 0 降级

- **WHEN** bidder_a 无章节标题行可识别(chapters=0),bidder_b 也 0
- **THEN** evidence.algorithm="tfidf_cosine_fallback_to_doc",degraded_to_doc_level=true;score 按 C7 同款算法计,AgentTask.status=succeeded

#### Scenario: 单侧章节数不足降级

- **WHEN** bidder_a 含 4 章节,bidder_b 含 2 章节(< MIN_CHAPTERS=3)
- **THEN** 触发降级;degrade_reason 注明 "chapters_b=2 < 3"

#### Scenario: 章节切分 + LLM 双降级

- **WHEN** 章节切分失败且 LLM 调用 timeout
- **THEN** evidence.degraded=true 且 evidence.degraded_to_doc_level=true;summary 说明两重降级

#### Scenario: 降级与 C7 text_similarity 独立

- **WHEN** 章节切分失败,section_similarity 写降级行;同轮 text_similarity(C7)正常写行
- **THEN** 两行 PairComparison 并存,judge.py 按各自维度权重计入 total_score;不合并证据

---

### Requirement: section_similarity evidence_json 结构

`PairComparison.evidence_json` 对 `dimension = 'section_similarity'` 的行 MUST 包含以下字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| `algorithm` | string | `"tfidf_cosine_chapter_v1"`(正常) / `"tfidf_cosine_fallback_to_doc"`(降级) |
| `doc_role` / `doc_id_a` / `doc_id_b` / `threshold` | 同 C7 | — |
| `chapters_a_count` | int | a 侧切章数(降级时为实际识别数或 0) |
| `chapters_b_count` | int | b 侧切章数 |
| `aligned_count` | int | `aligned_by='title'` 的章节对数(降级时 0) |
| `index_fallback_count` | int | `aligned_by='index'` 的章节对数(降级时 0) |
| `degraded_to_doc_level` | bool | 章节切分是否失败 |
| `degrade_reason` | string/null | 降级原因文案;正常为 null |
| `chapter_pairs` | array | 章节对明细,最多 20 条;每条 `{a_idx, b_idx, a_title, b_title, title_sim, aligned_by, chapter_score, is_chapter_ironclad, plagiarism_count}` |
| 以下继承 C7 字段 | | |
| `pairs_total` / `pairs_plagiarism` / `pairs_template` / `pairs_generic` | int | 跨全章节的段落对汇总(降级时是整文档级) |
| `degraded` | bool | LLM 是否降级(与 C7 同义) |
| `ai_judgment` | object/null | 同 C7 |
| `samples` | array | 按 sim 降序前 10 条段落对(同 C7 schema) |

#### Scenario: 正常 evidence_json

- **WHEN** section_similarity 章节切分成功并完成 LLM 调用
- **THEN** evidence.algorithm="tfidf_cosine_chapter_v1",degraded_to_doc_level=false,chapter_pairs 非空

#### Scenario: 降级 evidence_json

- **WHEN** section_similarity 章节切分失败
- **THEN** evidence.algorithm="tfidf_cosine_fallback_to_doc",degraded_to_doc_level=true,chapter_pairs=[],aligned_count=0

#### Scenario: chapter_pairs 20 条上限

- **WHEN** 对齐章节对数 > 20
- **THEN** chapter_pairs 按 chapter_score 降序截断到 20 条;aligned_count 记录实际对齐数(可 > 20)

---

### Requirement: section_similarity 环境变量

后端 MUST 支持以下环境变量动态读取:

- `SECTION_SIM_MIN_CHAPTERS`(默认 3)— 任一侧章节数 < 此值触发降级
- `SECTION_SIM_MIN_CHAPTER_CHARS`(默认 100)— 章节内字符 < 此值合并进前一章节
- `SECTION_SIM_TITLE_ALIGN_THRESHOLD`(默认 0.40)— title TF-IDF sim ≥ 此值算对齐成功(by title)

C7 既有环境变量被复用,C8 不重复定义同义 env:`TEXT_SIM_MIN_DOC_CHARS` / `TEXT_SIM_PAIR_SCORE_THRESHOLD` / `TEXT_SIM_MAX_PAIRS_TO_LLM`。

#### Scenario: MIN_CHAPTERS 默认值

- **WHEN** 未设置 SECTION_SIM_MIN_CHAPTERS
- **THEN** run() 使用 3 作为下界

#### Scenario: 运行期 monkeypatch 生效

- **WHEN** L1/L2 测试 monkeypatch.setenv("SECTION_SIM_MIN_CHAPTERS", "5")
- **THEN** run() 读取 5,章节数 < 5 即触发降级

---

### Requirement: structure_similarity 三维度算法

Agent `structure_similarity` 的 `run()` MUST 执行三个独立维度的结构相似度计算,纯程序化(不调用 LLM):

1. **目录结构维度**(仅作用于 docx 文档):
   - 复用 C8 `section_sim_impl.chapter_parser.extract_chapters` 切出两侧章节 ChapterBlock
   - 取每章 `title`,归一化(剥离 `第X章 / X.Y / 一、` 等序号前缀 + 去空白全角 + 统一标点)
   - 计算 LCS 长度,相似度 = `2 × LCS_len / (len_a + len_b)`
   - 任一侧归一化后章节数 < `STRUCTURE_SIM_MIN_CHAPTERS`(默认 3)→ 该维度不参与聚合(None)

2. **字段结构维度**(仅作用于 xlsx 文档):
   - 读两侧 `DocumentSheet.rows_json` 与 `merged_cells_json`
   - 按 `sheet_name` 配对两侧 sheet(相同名称为一对);未配对 sheet 不贡献分数
   - 对每对 sheet:列头 hash Jaccard(首个非空行归一化后字段集合)+ 每行非空列 bitmask 的 multiset Jaccard + merged_cells ranges 集合 Jaccard,按子权重(`STRUCTURE_SIM_FIELD_JACCARD_SUB_WEIGHTS`,默认 `0.4 / 0.3 / 0.3`)加权
   - 字段维度总分 = `max(per_sheet_sub_score)`(单 sheet 雷同即触发)
   - 两侧任一方 xlsx DocumentSheet 不存在 → 该维度不参与聚合(None)

3. **表单填充模式维度**(仅作用于 xlsx 文档):
   - 对每个 cell 归为 4 类 pattern:`N`(数字)/`D`(日期)/`T`(文本)/`_`(空)
   - 每行 pattern 串接为字符串(如 `"TN_N_D"`),两侧作为 multiset 计算 Jaccard
   - 按 sheet 配对同字段维度;填充维度总分 = `max(per_sheet_jaccard)`
   - 两侧任一方 xlsx DocumentSheet 不存在 → 该维度不参与聚合(None)

**维度聚合**:`STRUCTURE_SIM_WEIGHTS`(默认 `"0.4,0.3,0.3"`)三维度权重;参与维度按其原始权重重新归一化求加权平均,结果 × 100 得 Agent score。仅目录+填充参与时等效 `(dir × 0.4 + fill × 0.3) / 0.7 × 100`。

**is_ironclad**:任一维度 sub_score ≥ 0.90 且 Agent 总 score ≥ 85 → is_ironclad=True。

CPU 密集步骤(目录 LCS)MUST 走 `get_cpu_executor()`(与 C7/C8 共享 ProcessPoolExecutor)。字段/填充维度 Jaccard 运算较轻,不强制走 executor。

#### Scenario: 目录完全一致命中

- **WHEN** pair(A, B)两份 docx 章节标题序列完全相同(含规范化后),共 12 章节
- **THEN** PairComparison.score ≥ 60.0,evidence_json.algorithm = "structure_sim_v1",evidence_json.dimensions.directory.score ≥ 0.9,evidence_json.dimensions.directory.lcs_length ≥ 10

#### Scenario: 报价表填充结构一致命中

- **WHEN** pair(A, B)两份 xlsx 首个 sheet(名为"报价汇总")列头完全相同、空值位置完全相同、合并单元格 ranges 完全相同
- **THEN** PairComparison.score ≥ 60.0,evidence_json.dimensions.field_structure.score ≥ 0.8,evidence_json.dimensions.field_structure.per_sheet 含一条 sub_score ≥ 0.9 的条目

#### Scenario: 独立结构不误报

- **WHEN** pair(A, B)两份 docx 章节标题序列完全不同(LCS 占比 < 0.2)且两份 xlsx 列头、bitmask、merged_cells 均不重合
- **THEN** PairComparison.score < 30.0,is_ironclad = false

#### Scenario: 目录维度走 CPU executor

- **WHEN** 目录结构维度的 LCS 计算(章节数 m × n)
- **THEN** 通过 `get_cpu_executor()` 异步提交(loop.run_in_executor),不在主 asyncio 事件循环内阻塞 CPU

---

### Requirement: structure_similarity preflight

Agent `structure_similarity` preflight MUST 执行:

1. 双方均有同 file_role 的 BidDocument(复用 `_preflight_helpers.bidders_share_any_role`)
2. 双方选中角色下至少一侧有 docx 文档 **或** 至少一侧有 xlsx 文档(轻量 COUNT 查询,不做完整结构提取;走 `_preflight_helpers.bidders_share_role_with_ext`)

维度级提取失败不在 preflight 阶段触发 skip,下放到 `run()` 内部各维度单独判定。

#### Scenario: 同角色文档缺失 skip

- **WHEN** 任一侧无同 file_role 的 BidDocument
- **THEN** 返 `PreflightResult(status='skip', reason='缺少可对比文档')`

#### Scenario: 双方都无 docx 也无 xlsx 时 skip

- **WHEN** 双方共享角色下只有图片或 PDF,无任何 docx/xlsx 文件
- **THEN** 返 `PreflightResult(status='skip', reason='结构缺失')`

#### Scenario: 仅一侧有 docx 时 preflight 放行

- **WHEN** bidder_a 有 docx,bidder_b 仅有 xlsx(角色相同,但类型互补)
- **THEN** preflight 返 `ok`;run 内部目录维度因单侧 docx 缺失而 None,字段/填充维度同理单侧 xlsx 缺失而 None,可能 3 维度全 None → run 级 skip(score=0.0 + participating_dimensions=[])

---

### Requirement: structure_similarity 维度级与 Agent 级 skip 语义

Agent `structure_similarity` MUST 区分两级 skip:

- **维度级 skip**:单维度提取/计算失败(如 docx 章节数不足、xlsx DocumentSheet 不存在)→ 该维度 `dimensions.<dim>.score = null` 并标注 `reason` 字段;**不影响其他维度**;最终 Agent score 按参与维度的原始权重重新归一化计算
- **Agent 级 skip 两条路径**:
  - preflight 阶段双方无 docx/xlsx → `PreflightResult(status='skip', reason='结构缺失')`,engine 标 AgentTask.status=skipped,**不写 PairComparison**
  - run 阶段 3 维度全部 None(preflight 通过但 docx 章节数不足 + xlsx 无有效 sheet)→ run 仍正常完成,`AgentRunResult(score=0.0, summary="结构缺失:...")`,PairComparison.score=0.0 + `evidence.participating_dimensions=[]`(前端按 participating_dimensions 为空识别为"Agent 级 skip")

**与 C8 section_similarity 不同**:C9 **不做**"章节切分失败 → 降级到整文档粒度"这种降级,execution-plan §3 C9 兜底原文要求"跳过该维度,不假阳"。

#### Scenario: 仅字段维度失败

- **WHEN** 目录维度正常(LCS sim=0.8),字段维度 xlsx DocumentSheet 缺失(bidder_b 未回填),填充维度同理缺失
- **THEN** score = 0.8 × 100 = 80.0(仅目录参与,重归一化权重 1.0);evidence.participating_dimensions = ["directory"];evidence.dimensions.field_structure.score = null + reason = "xlsx_sheet_missing"

#### Scenario: 3 维度全 None 触发 run 级 skip

- **WHEN** preflight 通过(至少一侧有 docx/xlsx),但 run 阶段所有维度提取失败(如 docx 章节数不足 + xlsx 无有效 sheet)
- **THEN** run 返 `AgentRunResult(score=0.0, summary="结构缺失:...")`;PairComparison 写一行 score=0.0、`evidence.participating_dimensions=[]`;AgentTask.status=succeeded

#### Scenario: 不走 C8 式降级

- **WHEN** docx 章节数 < MIN_CHAPTERS=3
- **THEN** 目录维度 None,不走"整文档 TF-IDF 降级"分支;Agent 不 import 任何 text_sim_impl 模块

---

### Requirement: structure_similarity evidence_json 结构

`PairComparison.evidence_json` 对 `dimension = 'structure_similarity'` 的行 MUST 包含以下字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| `algorithm` | string | `"structure_sim_v1"` |
| `doc_role` | string | 参与检测的共享角色;多角色时用 `"role_a+role_b"` 拼接 |
| `doc_id_a` / `doc_id_b` | int[] | 参与检测的文档 id(可能多个,因三维度作用于不同 ext);docx 维度的 doc_id 和 xlsx 维度的 doc_id 可能不同 |
| `participating_dimensions` | string[] | 参与加权的维度名,子集 of `["directory", "field_structure", "fill_pattern"]` |
| `weights_used` | object | 实际使用的权重 `{"directory": 0.4, "field_structure": 0.3, "fill_pattern": 0.3}`(仅列参与维度) |
| `dimensions.directory.score` | float/null | 0~1 或 null(未参与) |
| `dimensions.directory.reason` | string/null | score=null 时的原因 |
| `dimensions.directory.titles_a_count` / `titles_b_count` | int | 两侧章节数 |
| `dimensions.directory.lcs_length` | int | LCS 长度 |
| `dimensions.directory.sample_titles_matched` | string[] | 前 10 条被 LCS 命中的章节标题(归一化前原文) |
| `dimensions.field_structure.score` | float/null | 0~1 或 null |
| `dimensions.field_structure.reason` | string/null | — |
| `dimensions.field_structure.per_sheet` | array | 每个配对 sheet 一条,`{sheet_name, header_sim, bitmask_sim, merged_cells_sim, sub_score}`,上限 5 sheet |
| `dimensions.fill_pattern.score` | float/null | 0~1 或 null |
| `dimensions.fill_pattern.reason` | string/null | — |
| `dimensions.fill_pattern.per_sheet` | array | 每个配对 sheet 一条,`{sheet_name, score, matched_pattern_lines, sample_patterns}`,上限 5 sheet;sample_patterns 上限 10 条 |

#### Scenario: 3 维度正常 evidence_json

- **WHEN** 双方均有 docx(章节提取成功)且均有 xlsx(sheet 成功配对)
- **THEN** participating_dimensions = ["directory", "field_structure", "fill_pattern"],dimensions 三个子对象 score 均非 null

#### Scenario: 单维度失败 evidence_json

- **WHEN** 仅目录参与(bidder_b xlsx DocumentSheet 缺失)
- **THEN** participating_dimensions = ["directory"];dimensions.field_structure.score = null + dimensions.field_structure.reason 非 null

#### Scenario: run 级 skip evidence_json

- **WHEN** run 阶段 3 维度全 None
- **THEN** PairComparison 行 score=0.0,evidence_json.participating_dimensions = [],evidence_json.dimensions 三维度 score 均 null

---

### Requirement: structure_similarity 环境变量

后端 MUST 支持以下环境变量动态读取:

- `STRUCTURE_SIM_MIN_CHAPTERS`(默认 3)— 目录维度:章节数 < 此值 → 该维度 None
- `STRUCTURE_SIM_MIN_SHEET_ROWS`(默认 2)— 字段/填充维度:每 sheet 非空行 < 此值 → 该 sheet 不参与配对
- `STRUCTURE_SIM_WEIGHTS`(默认 `"0.4,0.3,0.3"`)— 三维度权重(目录/字段/填充),逗号分隔 float
- `STRUCTURE_SIM_FIELD_JACCARD_SUB_WEIGHTS`(默认 `"0.4,0.3,0.3"`)— 字段维度三子信号权重(列头/bitmask/合并单元格)
- `STRUCTURE_SIM_MAX_ROWS_PER_SHEET`(默认 5000)— xlsx 持久化/消费时每 sheet 行数上限

**复用 C8 既有 env**:`SECTION_SIM_MIN_CHAPTER_CHARS=100`(通过 C8 `chapter_parser` 内部读取)。

#### Scenario: WEIGHTS 默认值

- **WHEN** 未设置 `STRUCTURE_SIM_WEIGHTS`
- **THEN** run() 使用 `(0.4, 0.3, 0.3)` 作为 (目录, 字段, 填充) 权重

#### Scenario: 运行期 monkeypatch 生效

- **WHEN** L1/L2 测试 `monkeypatch.setenv("STRUCTURE_SIM_MIN_CHAPTERS", "5")`
- **THEN** run() 读取 5,章节数 < 5 的那一侧 → 目录维度 None

#### Scenario: WEIGHTS 归一化失败时用默认

- **WHEN** 设置 `STRUCTURE_SIM_WEIGHTS="abc,xyz"`(无法 parse)
- **THEN** 代码 fallback 到默认 `(0.4, 0.3, 0.3)` 并打 warning 日志

---

### Requirement: metadata Agents 共享元数据提取器

后端 MUST 在 `app/services/detect/agents/metadata_impl/extractor.py` 提供 `extract_bidder_metadata(session, bidder_id) -> list[MetadataRecord]`,由 `metadata_author / metadata_time / metadata_machine` 三个 Agent 共同消费,不重复 query。

- 数据源:`DocumentMetadata` 表(C5 已持久化)+ C10 扩的 `template` 列
- 每条 `MetadataRecord` 对应 bidder 名下一个 BidDocument 的元数据
- 归一化字段(`author_norm` / `last_saved_by_norm` / `company_norm` / `template_norm` / `app_name` / `app_version`)通过 `metadata_impl.normalizer.nfkc_casefold_strip(s)` 计算:先 `unicodedata.normalize("NFKC", s)`,再 `.casefold()`,再 `.strip()`;空串视同 None
- 原值字段(`author_raw` / `template_raw`)保留供 evidence 给前端展示原文
- 时间字段 (`doc_created_at` / `doc_modified_at`) 不归一化,保持 timezone-aware datetime

**不缓存**:每个 Agent 各自调用 extractor;3 Agent 并发执行时不共享 cache(避免锁复杂度)。

#### Scenario: 正常提取

- **WHEN** bidder_id=5 名下有 3 份 BidDocument,每份 DocumentMetadata 存在
- **THEN** 返 `list[MetadataRecord]` 含 3 条,每条字段齐全(`bid_document_id` / `bidder_id` / `doc_name` / 6 个 `*_norm` + 2 个时间 + 2 个 raw)

#### Scenario: bidder 无 DocumentMetadata

- **WHEN** bidder_id=6 名下 BidDocument 均未 C5 解析完成(无 DocumentMetadata 行)
- **THEN** 返 `[]`;不抛错

#### Scenario: 字段为空串走 None

- **WHEN** DocumentMetadata.author = `""`(空串)
- **THEN** `MetadataRecord.author_norm is None`;`author_raw` 保留 `""` 或 None(按 DB 原值)

#### Scenario: NFKC 归一化

- **WHEN** DocumentMetadata.author = `"ＺＨＡＮＧ Ｓａｎ"`(全角)
- **THEN** `MetadataRecord.author_norm == "zhang san"`(NFKC 转半角 + casefold)

### Requirement: metadata_author 跨投标人字段聚类算法

Agent `metadata_author` 的 `run()` MUST 对 bidder_a / bidder_b 双方 `MetadataRecord` 列表执行三子字段碰撞:`author` / `last_saved_by` / `company`。

算法:
1. 对每个子字段,收集双方非空归一化值的集合 `set_a` / `set_b`;单侧空 → 该子字段不进 sub_scores(不算 0)
2. 共同值 `intersect = set_a ∩ set_b`;非空即命中,`hit_strength = |intersect| / min(|set_a|, |set_b|)`(∈ [0, 1])
3. 无命中 → `sub_score = 0.0`;有命中 → `sub_score = hit_strength`
4. 参与子字段按 `METADATA_AUTHOR_SUBDIM_WEIGHTS`(默认 `author=0.5, last_saved_by=0.3, company=0.2`)重归一化加权
5. 全三子字段均单侧缺失 → Agent 级 skip(`score=None` + reason=`"author/last_saved_by/company 三字段均缺失"`)

Agent `score = dim_score × 100`;`is_ironclad` 当 Agent `score >= METADATA_IRONCLAD_THRESHOLD`(默认 85)时 True。

evidence `hits` 数组每个共同值一条(`field` / `value`(原值)/ `normalized` / `doc_ids_a` / `doc_ids_b`);`hits` 上限 `METADATA_MAX_HITS_PER_AGENT`(默认 50)。

#### Scenario: 两 bidder 共享 author 命中

- **WHEN** bidder_a 3 文档 author 均 "张三";bidder_b 2 文档 author 均 "张三",其余字段不同
- **THEN** Agent score ≥ 50.0(author 子 strength=1.0 × 0.5/0.5 归一化 = 1.0 → ×100 = 100.0,但若 last_saved_by/company 两侧有值但无命中则 sub=0 拉低总分);evidence.hits 含一条 `field="author", value="张三"`,`doc_ids_a` 含 3 个 bidder_a 文档 id

#### Scenario: author 跨 bidder 精确一致 → is_ironclad

- **WHEN** bidder_a / bidder_b 三文档 author / last_saved_by / company 全部相同
- **THEN** Agent score = 100.0(三子 strength 均 1.0);is_ironclad=true

#### Scenario: author 均缺失走 Agent 级 skip

- **WHEN** bidder_a/b 所有 DocumentMetadata author=None, last_saved_by=None, company=None
- **THEN** run 返 `AgentRunResult(score=0.0, summary="元数据缺失:...")`;PairComparison 行 score=0.0、evidence.participating_fields=[];不抛错

#### Scenario: 变体不自动合并

- **WHEN** bidder_a author="张三",bidder_b author="张三 (admin)"(精确不等,归一化后仍不同)
- **THEN** sub_scores.author = 0.0(单 intersect 为空);不计命中

### Requirement: metadata_time 时间窗聚集与精确相等算法

Agent `metadata_time` 的 `run()` MUST 对 bidder_a/bidder_b 双方 `doc_modified_at` 与 `doc_created_at` 计算两子信号:

1. **modified_at 滑窗聚集**:
   - 合并双方所有 doc 的 `(modified_at, doc_id, side)` 排序
   - 滑窗宽度 `METADATA_TIME_CLUSTER_WINDOW_MIN`(默认 5 分钟)
   - 任何连续 2+ 条 `modified_at` 差 ≤ 窗口且**跨投标人**(窗口内 side 集合含 a 和 b)→ 记一条 TimeCluster
   - sub_score = `命中文档总数 / 双方总文档数`(clamp to [0, 1])
2. **created_at 精确相等**:
   - 双方 `doc_created_at` 按值分组;共同时间点即命中
   - sub_score = 同上占比

双子信号按 `METADATA_TIME_SUBDIM_WEIGHTS`(默认 modified=0.7, created=0.3)重归一化加权为 dim score。

维度级 skip:双方双字段都无数据 → `score=None, reason="doc_modified_at / doc_created_at 字段全缺失"`。

#### Scenario: 5 分钟内集中修改命中

- **WHEN** bidder_a 3 文档 modified_at 分别为 10:00, 10:02, 10:03;bidder_b 2 文档 modified_at 分别为 10:01, 10:04
- **THEN** 窗口内 5 文档形成一个跨 side 簇;sub_scores.modified_at_cluster > 0;Agent score > 0;evidence.hits 含一条 `dimension="modified_at_cluster"` 条目

#### Scenario: created_at 完全相同命中

- **WHEN** bidder_a doc1.created_at = 2026-03-01T12:00:00Z;bidder_b doc2.created_at = 2026-03-01T12:00:00Z(秒级精确相等)
- **THEN** sub_scores.created_at_match > 0;evidence.hits 含一条 `dimension="created_at_match"` 条目

#### Scenario: 时间窗不跨 bidder 不命中

- **WHEN** bidder_a 3 文档 modified_at 10:00, 10:01, 10:02(同 bidder 集中修改);bidder_b 文档 modified_at 距离 > 5 分钟
- **THEN** 虽 bidder_a 内部窗口内多文档,但无跨 side → sub_scores.modified_at_cluster = 0

#### Scenario: 窗口可 monkeypatch

- **WHEN** `monkeypatch.setenv("METADATA_TIME_CLUSTER_WINDOW_MIN", "30")` 后调 run()
- **THEN** window 读 30 分钟;30 分钟内的跨 bidder 聚集命中

#### Scenario: time 双字段全缺失 → Agent 级 skip

- **WHEN** bidder_a/b 所有 DocumentMetadata `doc_modified_at` 和 `doc_created_at` 均为 None
- **THEN** Agent run 返 `AgentRunResult(score=0.0, summary="元数据缺失:...")`;PairComparison.score=0.0 + evidence.participating_fields=[]

### Requirement: metadata_machine 机器指纹元组碰撞算法

Agent `metadata_machine` 的 `run()` MUST 对 bidder_a/bidder_b 双方 `(app_name, app_version, template_norm)` 三字段**元组精确碰撞**计算:

1. 每份文档构成 key = `(app_name, app_version, template_norm)`;**三字段任一为 None 视为不参与**(整份文档不贡献 machine 匹配)
2. 双方 tuples_a / tuples_b 分别按 key 聚合(同一 key 可能多个 doc)
3. 共同 key `common = keys_a ∩ keys_b`;非空即命中
4. `hit_strength = 命中 key 所覆盖的 doc 数 / 双方总 doc 数`(clamp [0, 1])
5. 双方任一方 tuples 为空(无完整三字段元组)→ 维度级 skip

Agent `score = hit_strength × 100`;evidence hits 每条为:
```
{
  "field": "machine_fingerprint",
  "value": {"app_name": ..., "app_version": ..., "template": ...},
  "doc_ids_a": [...],
  "doc_ids_b": [...]
}
```

#### Scenario: 三字段元组完全一致命中

- **WHEN** bidder_a 2 文档元组均 `("microsoft office word", "16.0000", "normal.dotm")`;bidder_b 1 文档元组相同
- **THEN** Agent score ≥ 85.0(hit_strength=1.0 → ×100 = 100);is_ironclad=true;evidence.hits 含 1 条 machine_fingerprint 元组

#### Scenario: 任一字段不同不命中

- **WHEN** bidder_a (Word, 16.0000, Normal.dotm);bidder_b (Word, 16.0000, CustomBid.dotx)
- **THEN** common = ∅;Agent score = 0.0;evidence.hits = []

#### Scenario: 某字段全缺失走 Agent 级 skip

- **WHEN** bidder_a/b 所有 DocumentMetadata template=None(三字段元组不完整)
- **THEN** tuples_a = tuples_b = {};run 返 score=0.0 + evidence.participating_fields=[]

#### Scenario: 部分文档元组不完整,部分完整

- **WHEN** bidder_a 3 文档,其中 2 个 template=None,1 个 template="normal.dotm";bidder_b 2 文档均 template="normal.dotm"
- **THEN** tuples_a 只含 1 个 doc 的元组(其他 2 doc 跳过);若与 tuples_b 命中,则 evidence.doc_ids_a 含那 1 个 doc id

### Requirement: metadata_* Agent 级 skip 与子检测 flag 语义

3 个 metadata Agent MUST 区分四种路径,按优先级依次判定:

1. **preflight skip**(engine 层处理):`bidder_has_metadata` 返 false → preflight 返 `skip`,engine 标 AgentTask.status=skipped,**不写 PairComparison**
2. **子检测 flag 关闭**:`METADATA_<DIM>_ENABLED=false` → run 不调 extractor/detector,PairComparison 行 `score=0.0` + `evidence.enabled=false`;AgentTask.status=succeeded(用户配置意图,非异常)
3. **维度级 skip(字段全缺失)**:preflight 通过(数据行存在)但实际字段全 None → dim_result.score=None;run 仍写 PairComparison 行 `score=0.0` + `evidence.participating_fields=[]` + `evidence.reason=<原因>`
4. **算法异常**:extractor/detector 抛异常 → run catch,PairComparison 行 `score=0.0` + `evidence.error=<类型:消息前 200 字>`;AgentTask.status=succeeded(不让单 Agent 异常影响整体检测流程)

区分 `participating_fields=[]` 与 `enabled=false`:前端据此可显示"数据不足"vs"已禁用";**前端按 `enabled=false` 优先识别**。

#### Scenario: flag 关闭不调 extractor

- **WHEN** `METADATA_AUTHOR_ENABLED=false` 且双方元数据足够
- **THEN** run 直接返 `AgentRunResult(score=0.0, summary="metadata_author 子检测已禁用")`;PairComparison 行 evidence.enabled=false;extractor 不被调用(L1 可通过 mock 验证)

#### Scenario: flag 关闭不阻塞其他子检测

- **WHEN** `METADATA_AUTHOR_ENABLED=false` 但 METADATA_TIME/MACHINE 仍启用
- **THEN** metadata_author 返 enabled=false;metadata_time / metadata_machine 正常跑各自算法

#### Scenario: 维度级 skip 与 flag 关闭区分

- **WHEN** `METADATA_AUTHOR_ENABLED=true` 但双方 author/last_saved_by/company 全 None
- **THEN** PairComparison 行 score=0.0 + evidence.participating_fields=[] + evidence.enabled=true + evidence.reason 非空;前端据此显示"数据不足"而非"已禁用"

#### Scenario: 异常路径写 error

- **WHEN** extractor 抛异常(模拟 DB 连接失败)
- **THEN** run catch 住,返 AgentRunResult(score=0.0);PairComparison 行 score=0.0 + evidence.error 非空(含类型+消息前 200 字);AgentTask.status=succeeded

### Requirement: metadata_* evidence_json 结构

`PairComparison.evidence_json` 对 `dimension in {'metadata_author', 'metadata_time', 'metadata_machine'}` 的行 MUST 包含以下统一核心字段,供前端合并 tab 渲染:

| 字段 | 类型 | 说明 |
|---|---|---|
| `algorithm` | string | `"metadata_author_v1"` / `"metadata_time_v1"` / `"metadata_machine_v1"` |
| `enabled` | bool | 对应 `METADATA_<DIM>_ENABLED` 配置值,false 时该 Agent 其他字段可为空/默认 |
| `score` | float/null | 0~1 归一化分(×100 即 Agent score);维度级 skip 时 null |
| `reason` | string/null | 维度级 skip 或 flag 禁用或异常时的描述 |
| `participating_fields` | string[] | 参与命中的子字段名,子集 of 各 Agent 自身定义的子字段 |
| `sub_scores` | object | 每子字段/子信号独立 score(0~1) |
| `hits` | array | 命中条目数组;每条结构因 Agent 不同见下 |
| `doc_ids_a` | int[] | bidder_a 参与检测的全部 BidDocument id |
| `doc_ids_b` | int[] | bidder_b 参与检测的全部 BidDocument id |
| `error` | string/null | 算法异常时的错误描述(类型:消息前 200 字);正常路径为 null 或缺省 |

`hits` 条目结构:

- `metadata_author`:`{field: "author"|"last_saved_by"|"company", value: <原值>, normalized: <归一化后>, doc_ids_a, doc_ids_b}`
- `metadata_time`:`{dimension: "modified_at_cluster"|"created_at_match", window_min?: int, doc_ids_a, doc_ids_b, times: string[]}`
- `metadata_machine`:`{field: "machine_fingerprint", value: {app_name, app_version, template}, doc_ids_a, doc_ids_b}`

`hits` 条目上限 `METADATA_MAX_HITS_PER_AGENT`(默认 50)。

#### Scenario: 正常命中 evidence_json

- **WHEN** metadata_author 命中 "张三"
- **THEN** evidence_json.algorithm="metadata_author_v1",enabled=true,score>0,participating_fields 含 "author",hits[0].field="author",hits[0].value="张三",hits[0].doc_ids_a 非空

#### Scenario: flag 关闭 evidence_json

- **WHEN** METADATA_MACHINE_ENABLED=false
- **THEN** evidence_json.algorithm="metadata_machine_v1",enabled=false,score=null 或 0;其他字段可缺省

#### Scenario: 维度级 skip evidence_json

- **WHEN** 三字段全缺失
- **THEN** evidence_json.enabled=true,score=null,reason 非空,participating_fields=[],hits=[]

### Requirement: metadata_* 环境变量

后端 MUST 支持以下环境变量动态读取(env 解析失败时 fallback 到默认值 + `logger.warning`):

- `METADATA_AUTHOR_ENABLED`(默认 `true`)— 布尔:`"false"`/`"0"` 视为 false,其余为 true
- `METADATA_TIME_ENABLED`(默认 `true`)
- `METADATA_MACHINE_ENABLED`(默认 `true`)
- `METADATA_TIME_CLUSTER_WINDOW_MIN`(默认 `5`)— int,单位分钟
- `METADATA_AUTHOR_SUBDIM_WEIGHTS`(默认 `"0.5,0.3,0.2"`)— 逗号分隔 float,顺序 `author,last_saved_by,company`
- `METADATA_TIME_SUBDIM_WEIGHTS`(默认 `"0.7,0.3"`)— 顺序 `modified_at_cluster,created_at_match`
- `METADATA_IRONCLAD_THRESHOLD`(默认 `85.0`)— Agent score ≥ 阈值 → is_ironclad
- `METADATA_MAX_HITS_PER_AGENT`(默认 `50`)— evidence hits 截断上限

#### Scenario: ENABLED 布尔解析

- **WHEN** `METADATA_AUTHOR_ENABLED="false"`(小写字串)
- **THEN** `load_author_config().enabled == False`

#### Scenario: WEIGHTS 解析失败走默认

- **WHEN** `METADATA_AUTHOR_SUBDIM_WEIGHTS="abc,xyz"` 不是合法 float
- **THEN** `load_author_config().subdim_weights == {"author": 0.5, "last_saved_by": 0.3, "company": 0.2}`;日志 warning

#### Scenario: 运行期 monkeypatch 生效

- **WHEN** L1/L2 测试 `monkeypatch.setenv("METADATA_TIME_CLUSTER_WINDOW_MIN", "15")`
- **THEN** 下一次调用 `load_time_config().window_min == 15`

### Requirement: _preflight_helpers.bidder_has_metadata machine 分支扩 template

`_preflight_helpers.bidder_has_metadata(session, bidder_id, require_field="machine")` MUST 在 C10 后扩展条件为 `app_version IS NOT NULL OR app_name IS NOT NULL OR template IS NOT NULL`(逻辑 OR)。

其他 `require_field` 值(`"author"` / `"modified"`)保持 C6 既有逻辑不变。

#### Scenario: template 非空即通过

- **WHEN** bidder 所有 DocumentMetadata app_version=None, app_name=None 但某文档 template="Normal.dotm"
- **THEN** `bidder_has_metadata(session, bidder_id, "machine") == True`

#### Scenario: 三字段全空不通过

- **WHEN** bidder 所有 DocumentMetadata app_version/app_name/template 全 None
- **THEN** `bidder_has_metadata(session, bidder_id, "machine") == False`;metadata_machine preflight 返 skip

### Requirement: price_consistency 共享报价提取器

后端 MUST 在 `app/services/detect/agents/price_impl/extractor.py` 提供 `extract_bidder_prices(session, bidder_id, cfg) -> dict[str, list[PriceRow]]`,由 `price_consistency` Agent 的 4 个子检测共同消费,不重复 query。

- 数据源:`PriceItem` 表(C5 已持久化)
- 返回按 `sheet_name` 分组的 PriceRow 列表,行内按 `row_index` 排序
- 每条 PriceRow 包含预计算字段:`tail_key`(通过 `normalize_item_name + split_price_tail` 计算)/ `item_name_norm`(NFKC+casefold+strip)/ `total_price_float`(Decimal → float 供 series 子检测)
- `cfg.max_rows_per_bidder`(默认 5000)为加载上限,超出截断防止极端文档拉爆内存
- **不读** `price_parsing_rule` 的 `currency` 和 `tax_included` 字段(Q2 决策:口径完全忽略)
- **不消费** `DocumentSheet` 表(Q4 决策:C11 只走 PriceItem)

#### Scenario: 正常提取

- **WHEN** bidder_id=5 名下 3 份 PriceItem 分布在 2 个 sheet("清单表":2 条,"商务价":1 条)
- **THEN** 返 `dict` 含 2 个 key,总行数 3;每条 PriceRow 含 `tail_key / item_name_norm / total_price_float` 字段

#### Scenario: bidder 无 PriceItem

- **WHEN** bidder_id=6 名下无任何 PriceItem 行
- **THEN** 返 `{}`;不抛错

#### Scenario: 异常样本行级 skip

- **WHEN** PriceItem.total_price=NULL,PriceItem.item_name=NULL
- **THEN** PriceRow.tail_key=None;item_name_norm=None;total_price_float=None;行仍在返回结果中供各子检测按需过滤

#### Scenario: max_rows_per_bidder 限流

- **WHEN** bidder 名下 10000 条 PriceItem,env `PRICE_CONSISTENCY_MAX_ROWS_PER_BIDDER=5000`
- **THEN** 返回总行数为 5000(按 `sheet_name, row_index` 顺序截取)

---

### Requirement: price_consistency normalizer 契约

后端 MUST 在 `app/services/detect/agents/price_impl/normalizer.py` 提供 3 个纯函数:

- `normalize_item_name(name: str | None) -> str | None`:`None` / 空串 → `None`;否则 `unicodedata.normalize("NFKC", s).casefold().strip()`,再判空串返 `None`
- `split_price_tail(total_price: Decimal | None, tail_n: int) -> tuple[str, int] | None`:返 `(尾 N 位字符串, 整数部分位长)`;Decimal 用 `int()` truncate 取整;异常样本(`None` / 非数值 / 负数)→ `None`;整数位长 < tail_n 时用 `zfill(tail_n)` 前补 0
- `decimal_to_float_safe(d: Decimal | None) -> float | None`:`None` → `None`;`Decimal` 转 `float` 失败(`InvalidOperation` 等)→ `None`

#### Scenario: NFKC 归一化

- **WHEN** name=`"钢筋 Φ12  "`(含全角 + 首尾空格)
- **THEN** 返 `"钢筋 φ12"`(NFKC 后 Φ → φ;strip;casefold)

#### Scenario: 组合 key 区分量级

- **WHEN** total_price=Decimal("1100"),tail_n=3
- **THEN** 返 `("100", 4)`(尾 3 位 "100",整数位长 4)

- **WHEN** total_price=Decimal("100"),tail_n=3
- **THEN** 返 `("100", 3)`(与上例尾数相同但整数位长不同,组合 key 不相等)

#### Scenario: 异常样本返 None

- **WHEN** total_price=None
- **THEN** split_price_tail 返 `None`

- **WHEN** total_price=Decimal("-50")
- **THEN** split_price_tail 返 `None`(负值视为异常)

---

### Requirement: price_consistency tail 尾数子检测算法

Agent `price_consistency` 的子检测 1 `tail` MUST 对双方 flatten 后的 PriceRow 列表做跨投标人尾数组合 key 碰撞。

算法:
1. flatten 两侧 PriceRow,过滤 `tail_key is None` 行(异常样本)
2. 两侧 tail_key 集合 `set_a` / `set_b`;任一侧空 → `score=None, reason="至少一侧无可比对报价行"`
3. 交集 `intersect = set_a ∩ set_b`;空 → `score=0.0`
4. 命中 → `hit_strength = |intersect| / min(|set_a|, |set_b|)`;hits 限流 `max_hits`(默认 20)
5. 子检测 `enabled=false` → 不执行,scorer 跳过

组合 key `(tail, int_len)` 的必要性:区分 ¥100 / ¥1100(尾 3 位都是 "100",整数位长 3 vs 4),避免不同量级跨行误撞。

#### Scenario: 3 家报价尾 3 位碰撞

- **WHEN** A 家 total_price 尾 3 位 {"880", "660"},B 家尾 3 位 {"880", "777"},整数位长 A/B 相同
- **THEN** intersect={("880", 6)};hit_strength = 1/2 = 0.5;`score=0.5`

#### Scenario: 不同量级不误撞

- **WHEN** A 尾数 "100" 整数位长 3(¥100),B 尾数 "100" 整数位长 4(¥1100)
- **THEN** 组合 key 不等,`score=0.0`

#### Scenario: 异常样本不假阳

- **WHEN** A 家 3 行 total_price 全为 NULL
- **THEN** tail_key 全 None,过滤后 set_a 空;`score=None, reason="至少一侧无可比对报价行"`

#### Scenario: flag 禁用

- **WHEN** env `PRICE_CONSISTENCY_TAIL_ENABLED=false`
- **THEN** tail detector 不执行;scorer 跳过该子检测,evidence `subdims.tail.enabled=false`

---

### Requirement: price_consistency amount_pattern 金额模式子检测算法

Agent `price_consistency` 的子检测 2 `amount_pattern` MUST 对双方 flatten 后的 PriceRow 构建 `(item_name_norm, unit_price)` 对集合,计算交集占比。

算法:
1. 仅 `item_name_norm is not None AND unit_price_raw is not None` 的行参与
2. 两侧对集合 `pairs_a` / `pairs_b`;任一侧空 → `score=None`
3. `strength = |intersect| / min(|pairs_a|, |pairs_b|)`
4. `strength >= threshold`(默认 0.5)→ `score=strength`;否则 `score=0.0`
5. hits 限流 `max_hits`

#### Scenario: 80% 明细单价相同

- **WHEN** A 家 10 行 (item_name, unit_price) 对,B 家 10 行,其中 8 对完全相同
- **THEN** strength = 8/10 = 0.8;`score=0.8`

#### Scenario: 单价相同但 item_name 不同不命中

- **WHEN** A 家 item_name="钢筋Φ12" unit_price=100,B 家 item_name="Φ12 螺纹钢" unit_price=100
- **THEN** item_name_norm 不同(NFKC 精确,语义变体不合并),该对不匹配;若其他行也无匹配则 `score=0.0`

#### Scenario: item_name NULL 行跳过

- **WHEN** A 家 3 行 item_name 均为 NULL(C5 归一化失败)
- **THEN** pairs_a 为空集;若 B 侧有对,`score=None, reason="至少一侧无 (item_name, unit_price) 有效对"`

#### Scenario: flag 禁用

- **WHEN** env `PRICE_CONSISTENCY_AMOUNT_PATTERN_ENABLED=false`
- **THEN** 不执行,scorer 跳过,evidence `subdims.amount_pattern.enabled=false`

---

### Requirement: price_consistency item_list 两阶段对齐子检测算法

Agent `price_consistency` 的子检测 3 `item_list` MUST 实施两阶段对齐策略:

**阶段 1(判定用同模板)**:两 bidder 满足
- sheet_name 集合相同(`set(grouped_a.keys()) == set(grouped_b.keys())`)
- 每个同名 sheet 的 PriceItem 数量相同

**阶段 1a(同模板,位置对齐)**:若满足阶段 1,按 `(sheet_name, row_index)` 配对行;对齐行"同项同价"命中 = `item_name_norm 相等 AND unit_price_raw 相等`;strength = matched / total_pairs

**阶段 1b(非同模板,item_name 归一精确匹配)**:否则 flatten 两侧 PriceRow,取 `item_name_norm is not None` 的集合交集;strength = `|intersect| / min(|names_a|, |names_b|)`

共通规则:
- `strength >= threshold`(默认 0.95)→ `score=strength`;否则 `score=0.0`
- evidence.hits.mode 标记 `"position"` 或 `"item_name"`,供前端区分路径
- hits 限流 `max_hits`

#### Scenario: 阶段 1a 命中

- **WHEN** A/B 同 1 个 sheet 各 10 行,位置对齐后 10 对全部 item_name_norm 相等 + unit_price_raw 相等
- **THEN** strength=1.0;`score=1.0`;evidence.hits.mode="position"

#### Scenario: 阶段 1a 轻微偏离不命中

- **WHEN** A/B 同模板 10 行,仅 5 对完全匹配(strength=0.5),threshold=0.95
- **THEN** `score=0.0`(未达阈值)

#### Scenario: 阶段 1b 命中

- **WHEN** A 20 行 B 18 行(数量不等),item_name 交集 18 项,min=18,strength=1.0
- **THEN** 走阶段 1b;`score=1.0`;evidence.hits.mode="item_name"

#### Scenario: 阶段 1 两侧全空

- **WHEN** A/B 均无有效 item_name
- **THEN** `score=None, reason="阶段 1b 至少一侧无 item_name"`

#### Scenario: flag 禁用

- **WHEN** env `PRICE_CONSISTENCY_ITEM_LIST_ENABLED=false`
- **THEN** 不执行,scorer 跳过

---

### Requirement: price_consistency series_relation 数列关系子检测算法

Agent `price_consistency` 的子检测 4 `series_relation` MUST 对同模板 pair(见 item_list 阶段 1 判定)的对齐行序列计算等比方差和等差变异系数。

算法:
1. 前置:同模板条件不满足(见 item_list 阶段 1)→ `score=None, reason="非同模板,series 子检测不适用"`
2. 遍历 `(sheet_name, row_index)` 对齐行,跳过 `total_price_float is None` 或 `a == 0` 的行
3. 若对齐样本数 < `min_pairs`(默认 3)→ `score=None, reason="对齐样本不足"`
4. 计算 `ratios = [b/a ...]` 的 `statistics.pvariance`;计算 `diffs = [b-a ...]` 的变异系数 `CV = pstdev / |mean|`(mean=0 或样本<2 → `CV=inf`)
5. `ratio_variance < ratio_variance_max`(默认 0.001)→ 等比命中,记 hits["mode"="ratio", "k"=mean(ratios)],`score = max(score, 1.0)`
6. `diff_cv < diff_cv_max`(默认 0.01)→ 等差命中,记 hits["mode"="diff", "diff"=mean(diffs)],`score = max(score, 1.0)`
7. 两者均不命中 → `score=0.0`
8. flag 禁用 → 不执行

**本子检测为 execution-plan §3 C11 原文未列的新增信号**(第一性原理审暴露的"水平关系/比例关系"真信号缺口),仅在同模板前提下工作。

#### Scenario: 等比关系命中

- **WHEN** 5 行对齐 ratios=[0.95, 0.95, 0.95, 0.95, 0.95](方差=0)
- **THEN** ratio_variance < 0.001;hit.mode="ratio" k=0.95;`score=1.0`

#### Scenario: 等差关系命中

- **WHEN** 5 行对齐 diffs=[10000, 10000, 10000, 10000, 10000],mean=10000 stdev=0
- **THEN** CV=0 < 0.01;hit.mode="diff" diff=10000;`score=1.0`

#### Scenario: 正常独立报价不命中

- **WHEN** 5 行对齐 ratios=[0.85, 1.1, 0.92, 1.15, 0.88](方差 > 0.01)
- **THEN** ratio_variance 远超阈值,CV 也远超阈值;`score=0.0`

#### Scenario: 对齐样本不足

- **WHEN** 同模板但 `min_pairs=3`,有效对齐样本仅 2 行
- **THEN** `score=None, reason="对齐样本不足(需 ≥ 3,实得 2)"`

#### Scenario: 非同模板 skip

- **WHEN** A/B 不满足同模板条件(sheet_name 不同或条数不等)
- **THEN** `score=None, reason="非同模板,series 子检测不适用"`

#### Scenario: flag 禁用

- **WHEN** env `PRICE_CONSISTENCY_SERIES_ENABLED=false`
- **THEN** 不执行,scorer 跳过

---

### Requirement: price_consistency scorer 合成规则

后端 MUST 在 `app/services/detect/agents/price_impl/scorer.py` 提供 `combine_subdims(results, cfg) -> (score, evidence)`:

- 子检测按 `PRICE_CONSISTENCY_SUBDIM_WEIGHTS`(默认 `0.25, 0.25, 0.3, 0.2`,顺序 tail/amount_pattern/item_list/series)加权合成
- `flag disabled` 或 `score=None` 的子检测 **不参与归一化**(对齐 C10 D10)
- 参与子检测的权重重归一化(即不强制总权重为 1,仅在参与子检测间做归一化)
- 最终 Agent score = `weighted / total_weight * 100.0`,范围 [0, 100]
- 全部子检测 skip 或 disabled → Agent 级 skip 哨兵:`score=0.0`, `evidence.enabled=false`, `participating_subdims=[]`

#### Scenario: 部分子检测参与

- **WHEN** tail `score=0.6`(参与),amount_pattern `score=None`(skip),item_list `score=1.0`(参与),series disabled
- **THEN** total_weight = 0.25+0.3 = 0.55;weighted = 0.6×0.25+1.0×0.3 = 0.45;score = 0.45/0.55×100 ≈ 81.82;`participating_subdims=["tail", "item_list"]`

#### Scenario: 全部子检测 skip

- **WHEN** 4 子检测全 `score=None`
- **THEN** `score=0.0`;`evidence.enabled=false`;`participating_subdims=[]`

#### Scenario: 全部子检测 disabled

- **WHEN** 4 flag 全 false
- **THEN** `score=0.0`;`evidence.enabled=false`;`participating_subdims=[]`

---

### Requirement: price_consistency Agent 级 skip 与行级兜底语义

Agent `price_consistency` MUST 实施三层兜底:

| 层级 | 触发条件 | 行为 |
|---|---|---|
| 行级 | `total_price` NULL / 非数值 / 负值;`item_name` NULL | 行过滤,不参与相应子检测 |
| 子检测级(数据不足) | 任一侧有效行为 0;series `min_pairs` 不足 | `score=None + reason`;不影响其他子检测 |
| 子检测级(flag disabled) | env `PRICE_CONSISTENCY_<SUB>_ENABLED=false` | 不执行 detector;scorer 跳过 |
| Agent 级(preflight skip) | 两 bidder 都无 PriceItem / 单侧无 | preflight 返 `skip`,不写 PairComparison |
| Agent 级(4 子全 skip) | 4 子检测全 `score=None` 或全 disabled | `score=0.0`,`evidence.enabled=false`,`participating_subdims=[]` |

**execution-plan §3 C11 兜底原文对齐**:
- "异常样本(非数值/缺失)→ 跳过不假阳" ↔ 行级 skip + 子检测级 `score=None`
- "归一化失败 → 标'口径不一致,无法比对'" ↔ 简化为:C11 不做口径归一化(Q2),不产生此路径;真口径分歧场景留 C14

#### Scenario: 行级 skip 不假阳

- **WHEN** PriceItem.total_price=NULL 的 5 行;其余行正常
- **THEN** 5 行在 tail/series 子检测被过滤,其他子检测照常;不因数据 NULL 导致任何子检测"命中"

#### Scenario: 子检测级 flag 禁用不影响其他子检测

- **WHEN** env `PRICE_CONSISTENCY_TAIL_ENABLED=false`,其他 3 flag true 且有数据
- **THEN** tail `evidence.subdims.tail.enabled=false` 且不参与 scorer;其他 3 子检测正常参与;Agent score > 0

#### Scenario: preflight skip 不写 PairComparison

- **WHEN** bidder_a 有 PriceItem,bidder_b 无
- **THEN** preflight 返 `skip` "未找到报价表";run 不执行;无 PairComparison 行写入

#### Scenario: Agent 级 skip 哨兵

- **WHEN** 4 子检测全返 `score=None`(均数据不足或全 disabled)
- **THEN** PairComparison 行写入,`score=0.0`,`summary="所有子检测均 skip"`,`evidence.enabled=false`,`participating_subdims=[]`

---

### Requirement: price_consistency evidence_json 结构

Agent `price_consistency` run 成功(含 Agent 级 skip 哨兵)时 PairComparison.evidence_json MUST 含:

| 字段 | 类型 | 说明 |
|---|---|---|
| `algorithm` | string | 固定 `"price_consistency_v1"`,区分 dummy |
| `doc_role` | string | `"priced"`(占位,C11 不按角色拆分) |
| `enabled` | bool | Agent 级开关:所有子 skip/disabled → false |
| `participating_subdims` | string[] | 参与 scorer 归一化的子检测 name 列表 |
| `subdims` | object | 4 子检测详情,key = tail / amount_pattern / item_list / series |
| `subdims.<name>.enabled` | bool | 该子检测 flag 开关状态 |
| `subdims.<name>.score` | float \| null | 子检测 hit_strength(0~1)或 null(数据不足 / disabled) |
| `subdims.<name>.reason` | string \| null | score=null 时的文字原因 |
| `subdims.<name>.hits` | object[] | 命中明细,结构随子检测不同 |

子检测 hits 结构:
- tail: `{tail: "880", int_len: 6, rows_a: [...], rows_b: [...]}`
- amount_pattern: `{item_name: "钢筋φ12", unit_price: "100.00"}`
- item_list: `{mode: "position" | "item_name", sheet?, row_a?, row_b?, item_name?}`
- series: `{mode: "ratio" | "diff", k?, variance?, diff?, cv?, pairs}`

#### Scenario: 正常命中 evidence

- **WHEN** 4 子检测均有数据,tail/item_list 命中
- **THEN** evidence_json 含 `algorithm="price_consistency_v1"`, `enabled=true`, `participating_subdims` 含 4 项,`subdims.tail.hits[0].tail="880"`,`subdims.item_list.hits[0].mode="position"`

#### Scenario: Agent 级 skip evidence

- **WHEN** 4 子检测全 skip
- **THEN** evidence_json 含 `algorithm="price_consistency_v1"`, `enabled=false`, `participating_subdims=[]`;`subdims` 仍含 4 子检测 stub,各 `score=null`

---

### Requirement: price_consistency 环境变量

Agent `price_consistency` MUST 读取以下 env 配置(含默认值,env 可覆盖):

| env | 默认值 | 说明 |
|---|---|---|
| `PRICE_CONSISTENCY_TAIL_ENABLED` | `true` | 子检测 1 tail 开关 |
| `PRICE_CONSISTENCY_AMOUNT_PATTERN_ENABLED` | `true` | 子检测 2 amount_pattern 开关 |
| `PRICE_CONSISTENCY_ITEM_LIST_ENABLED` | `true` | 子检测 3 item_list 开关 |
| `PRICE_CONSISTENCY_SERIES_ENABLED` | `true` | 子检测 4 series 开关 |
| `PRICE_CONSISTENCY_TAIL_N` | `3` | tail 子检测尾数位数 |
| `PRICE_CONSISTENCY_AMOUNT_PATTERN_THRESHOLD` | `0.5` | amount_pattern 命中阈值 |
| `PRICE_CONSISTENCY_ITEM_LIST_THRESHOLD` | `0.95` | item_list 命中阈值 |
| `PRICE_CONSISTENCY_SERIES_RATIO_VARIANCE_MAX` | `0.001` | 等比方差上限 |
| `PRICE_CONSISTENCY_SERIES_DIFF_CV_MAX` | `0.01` | 等差变异系数上限 |
| `PRICE_CONSISTENCY_SERIES_MIN_PAIRS` | `3` | series 子检测最低对齐样本 |
| `PRICE_CONSISTENCY_SUBDIM_WEIGHTS` | `0.25,0.25,0.3,0.2` | 4 子检测权重(逗号分隔;顺序 tail/amount_pattern/item_list/series) |
| `PRICE_CONSISTENCY_MAX_ROWS_PER_BIDDER` | `5000` | 单 bidder PriceItem 最大加载量(保护阈值) |
| `PRICE_CONSISTENCY_MAX_HITS_PER_SUBDIM` | `20` | 单子检测 evidence hits 限流 |

#### Scenario: 环境变量默认值

- **WHEN** 未设置任何 `PRICE_CONSISTENCY_*` env
- **THEN** 4 子检测 flag 均 true,TAIL_N=3,ITEM_LIST_THRESHOLD=0.95,权重 `(0.25, 0.25, 0.3, 0.2)`

#### Scenario: 权重字符串解析

- **WHEN** env `PRICE_CONSISTENCY_SUBDIM_WEIGHTS="0.2,0.2,0.4,0.2"`
- **THEN** config.weights = {"tail": 0.2, "amount_pattern": 0.2, "item_list": 0.4, "series": 0.2}

#### Scenario: 子检测单独关闭

- **WHEN** env `PRICE_CONSISTENCY_SERIES_ENABLED=false`,其他 3 true
- **THEN** config.enabled = {"tail": True, "amount_pattern": True, "item_list": True, "series": False};scorer 跳过 series

---

### Requirement: price_anomaly preflight 与样本聚合 helper

后端 MUST 在 `app/services/detect/agents/_preflight_helpers.py` 提供 `async def project_has_priced_bidders(session, project_id: int, min_count: int = 3) -> bool` helper,用单次 SQL COUNT(DISTINCT bidder_id) 查询"项目下 `parse_status='priced'` 且 price_items 非空的 bidder 数 ≥ min_count"。

`price_anomaly.preflight` MUST 调用此 helper;`min_count` 由 `PRICE_ANOMALY_MIN_SAMPLE_SIZE` env 控制。

#### Scenario: 项目有 3 家 bidder 均 priced

- **WHEN** 项目 P1 下 3 家 bidder,均 `parse_status='priced'` 且 price_items 非空
- **THEN** `project_has_priced_bidders(session, P1.id, 3)` 返 True;`price_anomaly.preflight` 返 `PreflightResult(status='ok')`

#### Scenario: 项目只有 2 家 priced

- **WHEN** 项目 P1 下 5 家 bidder,仅 2 家 `parse_status='priced'`,其余 3 家 `pending/failed`
- **THEN** helper 返 False;preflight 返 skip

#### Scenario: price_items 为空的 bidder 不计入样本

- **WHEN** 项目 P1 下 3 家 bidder `parse_status='priced'`,其中 1 家 price_items 表无行
- **THEN** helper 仅计入另 2 家;返 False(< 3)

---

### Requirement: price_anomaly 样本提取器

后端 MUST 在 `app/services/detect/agents/anomaly_impl/extractor.py` 提供 `aggregate_bidder_totals(session, project_id, cfg) -> list[BidderPriceSummary]`。

`BidderPriceSummary` TypedDict 字段:`bidder_id: int / bidder_name: str / total_price: float`。

`total_price` = 该 bidder 所有 `price_items.total_price` 之和(Decimal 聚合后 `float()` 转换);仅计入 `parse_status='priced'` 且有 price_items 的 bidder;按 `cfg.max_bidders`(默认 50)上限截取。

聚合顺序 MUST 按 bidder_id 升序(保证 L1/L2 测试结果可重现)。

#### Scenario: 5 家 bidder 均 priced 全部返

- **WHEN** 项目 P1 下 5 家 bidder 均 priced,各 price_items 总和分别为 100 / 105 / 98 / 70 / 102
- **THEN** 返 5 条 BidderPriceSummary,total_price 对应上述值

#### Scenario: parse 失败的 bidder 过滤掉

- **WHEN** 5 家 bidder 中 2 家 `parse_status='failed'`
- **THEN** 返 3 条 BidderPriceSummary,仅包含 priced 的 3 家

#### Scenario: max_bidders 截断

- **WHEN** 项目 60 家 bidder priced,`cfg.max_bidders=50`
- **THEN** 返 50 条(按 bidder_id 升序取前 50)

---

### Requirement: price_anomaly 偏离检测算法

后端 MUST 在 `app/services/detect/agents/anomaly_impl/detector.py` 提供 `detect_outliers(summaries: list[BidderPriceSummary], cfg) -> DetectionResult`。

算法:
1. `mean = sum(s.total_price for s in summaries) / len(summaries)`
2. 对每个 summary 计算 `deviation = (s.total_price - mean) / mean`
3. 根据 `cfg.direction` 判定 outlier:
   - `low`(本期实现):`deviation < -cfg.deviation_threshold` → outlier,`direction='low'`
   - `high`(预留):`deviation > cfg.deviation_threshold` → outlier,`direction='high'`
   - `both`(预留):`abs(deviation) > cfg.deviation_threshold` → outlier,`direction` 按正负号
4. 本期实现中 `direction` 字段若非 `low` MUST log warn 并 fallback 到 `low` 分支

`DetectionResult` TypedDict 字段:`mean: float / outliers: list[AnomalyOutlier]`。
`AnomalyOutlier` TypedDict 字段:`bidder_id: int / total_price: float / deviation: float / direction: str`。

`mean == 0` 时(所有 bidder 报价均为 0):detector MUST 返 `DetectionResult(mean=0.0, outliers=[])`,不抛 ZeroDivisionError。

#### Scenario: 5 家中 1 家偏低 30% 触发

- **WHEN** summaries 总价 [100, 105, 98, 70, 102],threshold=0.30,direction='low'
- **THEN** mean≈95.0;outliers 仅含 bidder D (70),deviation≈-0.263;**因阈值 0.30 严格大于等,-0.263 的绝对值 0.263 < 0.30 → 不触发**

#### Scenario: 5 家中 1 家偏低 35% 触发

- **WHEN** summaries 总价 [100, 105, 98, 60, 102],threshold=0.30,direction='low'
- **THEN** mean≈93.0;outliers 含 bidder D(60),deviation≈-0.355 → 触发

#### Scenario: 全部正常无 outlier

- **WHEN** summaries 总价 [100, 105, 98, 103, 102],threshold=0.30
- **THEN** outliers=[]

#### Scenario: 所有报价为 0 不抛异常

- **WHEN** summaries 总价 [0, 0, 0]
- **THEN** `DetectionResult(mean=0.0, outliers=[])`

#### Scenario: direction=high 本期 fallback 到 low

- **WHEN** env `PRICE_ANOMALY_DIRECTION=high`,summaries 有 1 家偏高 35%
- **THEN** log warn "direction=high not implemented, fallback to low";按 low 分支执行(无高偏离 outlier)

---

### Requirement: price_anomaly Agent 级 skip 与 evidence_json 结构

Agent `price_anomaly` MUST 实施三层兜底:

1. `PRICE_ANOMALY_ENABLED=false` → 早返不调 extractor;`score=0.0`,`evidence_json={algorithm, enabled: false, outliers: []}`
2. preflight 层:样本不足(< MIN_SAMPLE_SIZE)→ AgentTask status='skipped',summary='样本数不足...',不进入 run
3. run 层:extractor 返 < MIN_SAMPLE_SIZE(边缘场景,如并发下数据变化)→ Agent 级 skip 哨兵 `score=0.0 + participating_subdims=[] + skip_reason='sample_size_below_min'`,AgentTask 仍 status='succeeded'

run 成功(含 Agent 级 skip 哨兵)时 OverallAnalysis.evidence_json MUST 含:

| 字段 | 类型 | 说明 |
|---|---|---|
| `algorithm` | string | 固定 `"price_anomaly_v1"`,区分 dummy |
| `enabled` | bool | Agent 总开关状态 |
| `sample_size` | int | 实际参与计算的 bidder 数 |
| `mean` | float \| null | 群体均值;skip 时为 null |
| `outliers` | array | 异常 bidder 列表(见 AnomalyOutlier schema) |
| `baseline` | null | follow-up 占位(标底路径) |
| `llm_explanation` | null | follow-up 占位(C14 LLM 解释) |
| `participating_subdims` | array | 当前实现固定 `["mean"]`;Agent 级 skip 时为 `[]` |
| `skip_reason` | string \| absent | 仅 skip 哨兵路径含此字段 |
| `config` | object | 关键 config 回写(min_sample_size / deviation_threshold / direction),便于 evidence 审计 |

`outliers` 数组元素:

| 字段 | 类型 | 说明 |
|---|---|---|
| `bidder_id` | int | Bidder FK |
| `total_price` | float | 该 bidder 总价 |
| `deviation` | float | 相对均值偏离,负值表示低于均值 |
| `direction` | string | `"low"` / `"high"` |

Agent 级输出分数:`len(outliers) == 0` → score=0.0(无风险);否则 `score = min(100.0, len(outliers) * 30.0 + max(abs(o.deviation) for o in outliers) * 100)`(占位公式,judge 阶段可用 env `PRICE_ANOMALY_WEIGHT` 调权;C14 合成时可覆盖)。

#### Scenario: 正常命中 1 个 outlier

- **WHEN** run 成功,5 家中 1 家偏低 35%
- **THEN** evidence_json 含 `algorithm="price_anomaly_v1"`,`enabled=true`,`sample_size=5`,`outliers` 含 1 元素,`baseline=null`,`llm_explanation=null`;score > 0

#### Scenario: Agent 级 skip 哨兵

- **WHEN** extractor 返 2 条(< 3 min)
- **THEN** `score=0.0`,`participating_subdims=[]`,`skip_reason='sample_size_below_min'`,`outliers=[]`;AgentTask status='succeeded'

#### Scenario: ENABLED=false 早返

- **WHEN** env `PRICE_ANOMALY_ENABLED=false`
- **THEN** score=0.0,evidence `enabled=false`,`outliers=[]`;extractor 不调用

---

### Requirement: price_anomaly 环境变量

Agent `price_anomaly` MUST 读取以下 env 配置(含默认值,env 可覆盖):

| env | 默认 | 说明 |
|---|---|---|
| `PRICE_ANOMALY_ENABLED` | `true` | Agent 总开关 |
| `PRICE_ANOMALY_MIN_SAMPLE_SIZE` | `3` | 样本下限 |
| `PRICE_ANOMALY_DEVIATION_THRESHOLD` | `0.30` | 偏离阈值(小数,0.30 = 30%) |
| `PRICE_ANOMALY_DIRECTION` | `low` | 偏离方向;本期仅 `low` 实现,其他值 fallback + warn |
| `PRICE_ANOMALY_BASELINE_ENABLED` | `false` | 标底路径总开关(本期硬 false;设 true 则 warn "not implemented",仍走均值路径) |
| `PRICE_ANOMALY_MAX_BIDDERS` | `50` | 每项目最多处理 bidder 数 |
| `PRICE_ANOMALY_WEIGHT` | `1.0` | judge 合成权重占位(C14 可覆盖) |

env 加载 MUST 在 `anomaly_impl/config.py::load_anomaly_config()` 完成;非法值(如负阈值 / 非正整数 sample_size)MUST 抛 `ValueError` 在模块加载期暴露,不静默 fallback。

#### Scenario: 默认配置加载

- **WHEN** 无 `PRICE_ANOMALY_*` env 设置
- **THEN** `load_anomaly_config()` 返 `AnomalyConfig(enabled=True, min_sample_size=3, deviation_threshold=0.30, direction='low', baseline_enabled=False, max_bidders=50, weight=1.0)`

#### Scenario: env 覆盖阈值

- **WHEN** env `PRICE_ANOMALY_DEVIATION_THRESHOLD=0.20`
- **THEN** `load_anomaly_config().deviation_threshold == 0.20`

#### Scenario: 非法负阈值抛错

- **WHEN** env `PRICE_ANOMALY_DEVIATION_THRESHOLD=-0.10`
- **THEN** `load_anomaly_config()` 抛 `ValueError("deviation_threshold must be > 0")`

#### Scenario: baseline_enabled=true 警告

- **WHEN** env `PRICE_ANOMALY_BASELINE_ENABLED=true`
- **THEN** `load_anomaly_config()` log warn "baseline path not implemented in C12, follow-up";config.baseline_enabled=True 但 run 不读此字段

### Requirement: error_consistency 关键词抽取与跨投标人交叉搜索

`error_consistency` Agent MUST 在 `app/services/detect/agents/error_impl/` 子包提供:

1. **`keyword_extractor.extract_keywords(bidder, downgrade: bool) -> list[str]`**:
   - 正常模式(downgrade=False):从 `bidder.identity_info` 抽 `公司全称 / 简称 / 关键人员姓名[] / 资质编号[]` 4 类字段值,平铺为字符串列表
   - 降级模式(downgrade=True):返 `[bidder.name]` 单元素列表(贴 spec §F-DA-02 "用投标人名称做关键词交叉搜索")
   - 长度过滤:整词 `len < ERROR_CONSISTENCY_MIN_KEYWORD_LEN`(默认 2)的丢弃(避免单字符碰撞,RISK-19 防护)
   - 去重 + NFKC 归一化

2. **`intersect_searcher.search(ctx, pair_a, pair_b) -> list[SuspiciousSegment]`**:
   - 取 A 的关键词在 B 的 `document_texts.paragraphs`(数组)+ `document_texts.header_footer.headers + footers`(数组并集)中做子串匹配
   - 取 B 的关键词在 A 的同样字段做反向匹配
   - 双向命中合并去重,每条 hit 含 `{paragraph_text, doc_id, doc_role, position("body"|"header"|"footer"), matched_keywords[], source_bidder_id}`
   - 候选段落总数上限 `ERROR_CONSISTENCY_MAX_CANDIDATE_SEGMENTS`(默认 100,RISK-19 token 爆炸防护);超限按 `len(matched_keywords)` 倒序截断

3. **`run()` 主流程**:对项目内全部 bidder 两两 (A, B),依次调 `extract_keywords` → `intersect_searcher.search` → `llm_judge.call_l5`,产出 PairComparison 行(global 型 Agent 也可能产 pair 行,贴 spec §F-DA-02 "两两比对")

#### Scenario: 正常模式抽 4 类字段

- **WHEN** bidder.identity_info = `{"company_name": "甲建设", "short_name": "甲", "key_persons": ["张三", "李四"], "credentials": ["AB123"]}`,downgrade=False
- **THEN** `extract_keywords` 返 `["甲建设", "甲", "张三", "李四", "AB123"]` 经过滤后(短词 "甲" 被丢弃 → `["甲建设", "张三", "李四", "AB123"]`)

#### Scenario: 降级模式只用 bidder.name

- **WHEN** bidder.identity_info = None,downgrade=True
- **THEN** `extract_keywords` 返 `[bidder.name]`

#### Scenario: 双向交叉搜索

- **WHEN** A 关键词 ["张三"] 出现在 B.paragraphs[3];B 关键词 ["乙公司"] 出现在 A.header_footer.footers[0]
- **THEN** `intersect_searcher.search` 返 2 条 SuspiciousSegment,分别标 source_bidder=A/B 和 position=body/footer

#### Scenario: 候选段落超 100 截断

- **WHEN** 双向命中产生 250 条 SuspiciousSegment
- **THEN** 按 `len(matched_keywords)` 倒序截断到 100 条;evidence 标 `truncated=true, original_count=250`

### Requirement: error_consistency L-5 LLM 调用契约与铁证判定

`error_consistency` MUST 调 L-5 LLM 做交叉污染深度判断:

1. **`llm_judge.call_l5(segments: list[SuspiciousSegment], bidder_a, bidder_b) -> LLMJudgment`**:
   - prompt 输入:双方名称 + 候选段落原文片段(spec §L-5)
   - 期望 LLM 返 JSON:`{"is_cross_contamination": bool, "evidence": [{"type": "公司名混入"|"人员名混入"|"案例共用"|"错别字共用", "snippet": str, "position": str}], "direct_evidence": bool, "confidence": float}`
   - 走 `tests/fixtures/llm_mock.py::call_llm_l5`(测试)/ 实际 LLM provider(生产)
   - 重试 `ERROR_CONSISTENCY_LLM_MAX_RETRIES`(默认 2)次

2. **铁证标记规则**:LLM 返 `direct_evidence=true` AND `is_cross_contamination=true` → evidence_json 顶层 `has_iron_evidence=True`(judge 读 OverallAnalysis.evidence_json 升铁证);pair 级 `is_iron_evidence=True` 写入 evidence.pair_results[i]。否则 `has_iron_evidence=False`

3. **JSON 解析容错**:JSON 格式错误 → 视为 LLM 失败走兜底路径(见"降级与失败兜底" Requirement)

#### Scenario: L-5 返铁证

- **WHEN** L-5 mock 返 `{"is_cross_contamination": true, "direct_evidence": true, ...}`
- **THEN** evidence_json 顶层 `has_iron_evidence = True`;evidence.pair_results[0].is_iron_evidence = True;evidence.llm_judgment.direct_evidence = True

#### Scenario: L-5 返非铁证但污染

- **WHEN** L-5 mock 返 `{"is_cross_contamination": true, "direct_evidence": false, ...}`
- **THEN** evidence_json 顶层 `has_iron_evidence = False`;evidence.llm_judgment 完整保存;score 按公式包含 LLM 加分但不强制铁证

#### Scenario: L-5 返 JSON 格式错误

- **WHEN** L-5 mock 返非合法 JSON 字符串
- **THEN** 重试 2 次后视为 LLM 失败,走兜底路径(下一 Requirement 描述)

### Requirement: error_consistency 降级路径与 LLM 失败兜底

`error_consistency` Agent MUST 实现两条独立兜底路径,覆盖 RISK-19 / RISK-20:

1. **preflight downgrade(identity_info 缺失)**:
   - preflight 检查全部 bidder `identity_info` — 全部缺失 → preflight 返 `downgrade`(贴现有 preflight Requirement);ctx.downgrade = True
   - run 内部仍调 `extract_keywords(bidder, downgrade=True)` 用 bidder.name + 仍调 `intersect_searcher.search` + **仍调 L-5 LLM**(贴 spec §F-DA-02 "降级模式不做铁证判定" — 降级是"不做铁证",不是"不调 LLM")
   - 但降级模式 `is_iron_evidence` 强制 = False(不论 L-5 返什么);evidence 标 `downgrade_mode=true`,summary 含 "降级检测"

2. **L-5 LLM 调用失败**(多次重试仍异常 / JSON 解析失败 / 超时):
   - 仅展示程序层关键词命中 evidence;不调用铁证判定;score 公式扣减 LLM 那部分(score = `min(100, hit_segment_count * 20)`,无 LLM 加分)
   - evidence 标 `llm_failed=true, llm_failure_reason=str`;summary 含 "AI 研判暂不可用"
   - 覆盖 RISK-20(L-1 失败致铁证静默跳过 → 降级运行而非跳过)

#### Scenario: identity_info 全缺降级仍调 L-5

- **WHEN** ctx.all_bidders 全部 identity_info=None,preflight 返 downgrade,run 被调用
- **THEN** `extract_keywords` 用 bidder.name;`call_l5` 仍被调用;但 `is_iron_evidence` 强制 False;evidence.downgrade_mode = True

#### Scenario: L-5 LLM 失败仅展示关键词命中

- **WHEN** L-5 mock 模拟超时 + 重试 2 次仍失败
- **THEN** `is_iron_evidence` = False;evidence.llm_failed = True;score = `min(100, hit_count * 20)`;summary 含 "AI 研判暂不可用"

### Requirement: error_consistency Agent 级 skip 与 evidence_json 结构

Agent `error_consistency` MUST 在以下三类场景走 Agent 级 skip 哨兵或早返:

- preflight 返 `skip`(`len(ctx.all_bidders) < 2`)→ Agent skip,不调 run
- run 内部检测无任何 bidder 有可抽关键词(降级模式连 bidder.name 也空)→ skip 哨兵 `score=0.0`, `participating_subdims=[]`, `skip_reason="no_extractable_keywords"`
- env `ERROR_CONSISTENCY_ENABLED=false` → 早返不执行 run,evidence.enabled=false

evidence_json 顶层结构(每对 PairComparison.evidence_json):

```json
{
  "enabled": true,
  "algorithm_version": "error_consistency_v1",
  "downgrade_mode": false,
  "llm_failed": false,
  "llm_failure_reason": null,
  "suspicious_segments": [
    {"paragraph_text": "...", "doc_id": 12, "doc_role": "technical", "position": "body",
     "matched_keywords": ["张三", "AB123"], "source_bidder_id": 5}
  ],
  "truncated": false,
  "original_count": 23,
  "llm_judgment": {
    "is_cross_contamination": true,
    "direct_evidence": true,
    "evidence": [...],
    "confidence": 0.85
  } | null,
  "llm_explanation": null,
  "skip_reason": null,
  "participating_subdims": ["keyword_intersect", "llm_l5"]
}
```

#### Scenario: ENABLED=false 早返

- **WHEN** `ERROR_CONSISTENCY_ENABLED=false`
- **THEN** Agent 早返;evidence.enabled = false;不调 extractor / searcher / llm

#### Scenario: 无可抽关键词 skip 哨兵

- **WHEN** 全部 bidder identity_info=None 且 bidder.name=""(极端场景)
- **THEN** AgentRunResult.score = 0.0;evidence.participating_subdims = [];evidence.skip_reason = "no_extractable_keywords"

### Requirement: error_consistency 环境变量

`error_consistency` MUST 暴露 5 个 env(关键参数严格校验,次要参数 warn fallback):

| env | 默认 | 类型 | 校验 |
|---|---|---|---|
| `ERROR_CONSISTENCY_ENABLED` | true | bool | 任意 |
| `ERROR_CONSISTENCY_MAX_CANDIDATE_SEGMENTS` | 100 | int > 0 | 严格,违反 raise ValueError |
| `ERROR_CONSISTENCY_MIN_KEYWORD_LEN` | 2 | int > 0 | 严格 |
| `ERROR_CONSISTENCY_LLM_TIMEOUT_S` | 30 | int > 0 | 宽松,< 0 → warn fallback 30 |
| `ERROR_CONSISTENCY_LLM_MAX_RETRIES` | 2 | int >= 0 | 宽松 |

#### Scenario: 关键 env 非法 raise

- **WHEN** `ERROR_CONSISTENCY_MAX_CANDIDATE_SEGMENTS=-5`
- **THEN** `ErrorConsistencyConfig.from_env()` 抛 ValueError

#### Scenario: 次要 env 非法 warn fallback

- **WHEN** `ERROR_CONSISTENCY_LLM_TIMEOUT_S=-10`
- **THEN** logger.warning 记录;config.llm_timeout_s = 30(默认)

### Requirement: image_reuse MD5 + pHash 双路算法

`image_reuse` Agent MUST 在 `app/services/detect/agents/image_impl/` 子包提供:

1. **小图过滤**:SQL 查询 `document_images` 时直接 WHERE `width >= IMAGE_REUSE_MIN_WIDTH AND height >= IMAGE_REUSE_MIN_HEIGHT`(默认 32),剔除小 icon / 装饰图

2. **MD5 精确双路**(优先):跨 bidder 两两 INNER JOIN `document_images.md5`,完全相同 → `MD5Match{md5, doc_id_a, doc_id_b, position_a, position_b, bidder_a_id, bidder_b_id}`,`hit_strength=1.0`,`match_type="byte_match"`

3. **pHash 感知双路**(在 MD5 未命中的图集合上):用 `imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)` 计算 Hamming distance;距离 ≤ `IMAGE_REUSE_PHASH_DISTANCE`(默认 5)→ `PHashMatch{phash_a, phash_b, distance, ...}`,`hit_strength = 1 - distance / 64`,`match_type="visual_similar"`

4. **去重**:同一 (doc_a, doc_b) 图对在 MD5 路命中后,不再进 pHash 路(避免重复)

5. **MAX_PAIRS 上限**(默认 10000):跨 bidder 图片对数超限按 `hit_strength` 倒序截断;evidence 标 `truncated=true`

6. **不引 L-7 LLM 非通用图判断**:本期 evidence 占位 `llm_non_generic_judgment: null`(留 follow-up 回填,届时 `is_iron_evidence` 由 L-7 判定升)

7. **分数公式**(占位):`min(100, md5_match_count * 30 + sum(phash_hit_strength) * 10)`

#### Scenario: MD5 命中字节匹配

- **WHEN** A.images 与 B.images 有 1 张 md5 相同
- **THEN** evidence.md5_matches 含 1 条 `{md5, hit_strength=1.0, match_type="byte_match"}`;score >= 30

#### Scenario: pHash 命中视觉相似

- **WHEN** A.images 与 B.images 无 md5 相同,但有 1 对 phash Hamming distance = 3
- **THEN** evidence.phash_matches 含 1 条 `{distance=3, hit_strength≈0.953, match_type="visual_similar"}`

#### Scenario: 小图被过滤

- **WHEN** A 与 B 各有 1 张 16x16 的 icon md5 相同
- **THEN** SQL 直接过滤,evidence.md5_matches = []

#### Scenario: MAX_PAIRS 截断

- **WHEN** 跨 bidder 图片对计算出 25000 对命中
- **THEN** 按 hit_strength 倒序截断到 10000;evidence.truncated=true, original_count=25000

#### Scenario: image_reuse 不升铁证

- **WHEN** 任意 MD5/pHash 命中
- **THEN** evidence_json 顶层无 `has_iron_evidence=true`(本期不做 L-7);evidence.llm_non_generic_judgment = null

### Requirement: image_reuse Agent 级 skip 与 evidence_json 结构

Agent `image_reuse` MUST 在以下场景走 Agent 级 skip 哨兵或早返:

- preflight 返 `skip`(< 2 bidder 有图片)→ Agent skip
- env `IMAGE_REUSE_ENABLED=false` → 早返,evidence.enabled=false
- run 内部小图过滤后实际可比对图集合不足(单 bidder 仅 0 张大图)→ skip 哨兵 `score=0.0, participating_subdims=[], skip_reason="no_comparable_images_after_size_filter"`

evidence_json 顶层结构(写入 OverallAnalysis,global 型):

```json
{
  "enabled": true,
  "algorithm_version": "image_reuse_v1",
  "md5_matches": [
    {"md5": "abc...", "doc_id_a": 12, "doc_id_b": 34,
     "bidder_a_id": 5, "bidder_b_id": 7, "position_a": "body", "position_b": "body",
     "hit_strength": 1.0, "match_type": "byte_match"}
  ],
  "phash_matches": [
    {"phash_a": "ff00...", "phash_b": "ff01...", "distance": 3, "hit_strength": 0.953,
     "doc_id_a": 12, "doc_id_b": 34, "bidder_a_id": 5, "bidder_b_id": 7,
     "match_type": "visual_similar"}
  ],
  "truncated": false,
  "original_count": 5,
  "llm_non_generic_judgment": null,
  "llm_explanation": null,
  "skip_reason": null,
  "participating_subdims": ["md5_exact", "phash_hamming"]
}
```

#### Scenario: ENABLED=false 早返

- **WHEN** `IMAGE_REUSE_ENABLED=false`
- **THEN** Agent 早返,evidence.enabled = false

#### Scenario: 全部小图被过滤后 skip 哨兵

- **WHEN** 全部 bidder 仅有 16x16 装饰小图,过滤后 0 张可比对
- **THEN** AgentRunResult.score=0.0,evidence.skip_reason="no_comparable_images_after_size_filter"

### Requirement: image_reuse 环境变量

`image_reuse` MUST 暴露以下 env(关键参数严格校验,次要参数 warn fallback):

| env | 默认 | 类型 | 校验 |
|---|---|---|---|
| `IMAGE_REUSE_ENABLED` | true | bool | 任意 |
| `IMAGE_REUSE_PHASH_DISTANCE_THRESHOLD` | 5 | int 0~64 | 严格,违反 raise |
| `IMAGE_REUSE_MIN_WIDTH` | 32 | int > 0 | 严格 |
| `IMAGE_REUSE_MIN_HEIGHT` | 32 | int > 0 | 严格 |
| `IMAGE_REUSE_MAX_PAIRS` | 10000 | int > 0 | 宽松,< 1 → warn fallback 10000 |

#### Scenario: 关键 env 非法 raise

- **WHEN** `IMAGE_REUSE_PHASH_DISTANCE_THRESHOLD=128`
- **THEN** `ImageReuseConfig.from_env()` 抛 ValueError(超 0~64 范围)

### Requirement: style L-8 两阶段 LLM 算法

`style` Agent MUST 在 `app/services/detect/agents/style_impl/` 子包提供:

1. **`sampler.sample(ctx, bidder) -> list[str]`**:
   - 仅取 bidder 的 `technical` 角色文档(`bid_documents.doc_role='technical'`,贴 spec §L-8 "技术方案类")
   - 全文段落集合做 TF-IDF 训练(`TfidfVectorizer`)→ 计算每段平均 IDF 权重 → 过滤掉 IDF 低于 `STYLE_TFIDF_FILTER_RATIO`(默认 0.3,即低 30% 高频通用段落,贴 spec §L-8 "TF-IDF 过滤掉高频通用段落如法规条文")
   - 剩余段落均匀抽样 `STYLE_SAMPLE_PER_BIDDER`(默认 8)段;每段过长截断到 300 字、过短(< 100 字)丢弃,贴 spec L-8 "5-10 段,每段 100-300 字"
   - 抽样不足 `min_sample`(默认 3 段)的 bidder 标 `insufficient_sample=true`

2. **`llm_client.call_l8_stage1(bidder_name, sampled_paragraphs) -> StyleFeatureBrief`**:
   - 每 bidder 1 次 LLM 调用,返 `{"用词偏好": str, "句式特点": str, "标点习惯": str, "段落组织": str}`
   - 走 `tests/fixtures/llm_mock.py::call_l8_stage1`

3. **`llm_client.call_l8_stage2(briefs: list[StyleFeatureBrief]) -> GlobalComparison`**:
   - 全部 bidder 摘要一次 LLM 比对,返 `{"consistent_groups": [{"bidder_ids": [1,2], "consistency_score": 0.85, "typical_features": str}], "limitation_note": str}`
   - 走 `tests/fixtures/llm_mock.py::call_l8_stage2`

4. **分数公式**(占位):`min(100, len(consistent_groups) * 30 + max(group.consistency_score * 100 for group in consistent_groups, default=0) * 0.5)`

5. **局限性说明**(spec §F-DA-06 强制要求):evidence.limitation_note 固定写入 `"风格一致可能源于同一主体操控,也可能源于委托同一代写服务,需结合其他维度综合判断"`

#### Scenario: Stage1 + Stage2 全成功

- **WHEN** 3 bidder 各有 ≥ 8 段技术段落,L-8 mock Stage1 返 3 brief,Stage2 返 1 consistent_group [bidder_1, bidder_2]
- **THEN** evidence.style_features_per_bidder = 3 brief;evidence.global_comparison.consistent_groups 含 1 group;evidence.limitation_note 已填

#### Scenario: 抽样后高频段落被过滤

- **WHEN** bidder 100 段中 70 段为通用法规条文(IDF 低)
- **THEN** sampler 过滤后剩 30 段,从中抽 8 段送 Stage1

#### Scenario: 单 bidder 抽样不足

- **WHEN** bidder.technical 文档仅有 2 段 100~300 字段落
- **THEN** sampler 标 `insufficient_sample=true`;Stage1 仍调用但 brief 标 `low_confidence`(简化:本期不强制 skip 该 bidder,evidence 标记)

### Requirement: style >20 bidder 自动分组

`style` Agent MUST 在 `len(ctx.all_bidders) > STYLE_GROUP_THRESHOLD`(默认 20)时按以下规则自动分组(贴 spec §F-DA-06 ">20 投标人时自动分组以避免超出 context 窗口"):

- 按 `bidder_id` 升序切片为 `ceil(N/20)` 组,每组 ≤ 20 个 bidder
- 每组独立做 Stage1(仍每 bidder 1 次调用)+ Stage2(每组 1 次调用)
- **不跨组比较**(简化版,贴 design.md D6 "完整跨组算法留 follow-up")
- evidence.grouping_strategy = `"grouped"`(< 20 时为 `"single"`);evidence.group_count = `ceil(N/20)`
- 5 家典型场景不触发分组路径(grouping_strategy="single")

#### Scenario: 25 bidder 切 2 组

- **WHEN** ctx.all_bidders 含 25 个 bidder,STYLE_GROUP_THRESHOLD=20
- **THEN** 第 1 组 bidder_id 升序前 20 个,第 2 组后 5 个;Stage1 调 25 次,Stage2 调 2 次;evidence.grouping_strategy="grouped", group_count=2

#### Scenario: 5 bidder 不分组

- **WHEN** ctx.all_bidders 含 5 个 bidder
- **THEN** 直接 Stage1 5 次 + Stage2 1 次;evidence.grouping_strategy="single"

### Requirement: style Agent 级 skip 与 evidence_json 结构

Agent `style` MUST 在以下场景走 Agent 级 skip 哨兵或早返(贴 spec §F-DA-06 "任一阶段 LLM 失败则整个维度跳过"):

- preflight 返 `skip`(< 2 bidder 有 technical 文档)→ Agent skip
- env `STYLE_ENABLED=false` → 早返,evidence.enabled=false
- Stage1 任一 bidder LLM 调用失败(重试后仍失败)→ Agent skip 哨兵 `score=0.0, participating_subdims=[], skip_reason="L-8 Stage1 LLM 调用失败"`
- Stage2 LLM 调用失败 → Agent skip 哨兵 `score=0.0, participating_subdims=[], skip_reason="L-8 Stage2 LLM 调用失败"`

evidence_json 顶层结构(写入 OverallAnalysis):

```json
{
  "enabled": true,
  "algorithm_version": "style_v1",
  "grouping_strategy": "single",
  "group_count": 1,
  "style_features_per_bidder": {
    "5": {"用词偏好": "...", "句式特点": "...", "标点习惯": "...", "段落组织": "...", "low_confidence": false}
  },
  "global_comparison": {
    "consistent_groups": [
      {"bidder_ids": [5, 7], "consistency_score": 0.85, "typical_features": "..."}
    ]
  },
  "limitation_note": "风格一致可能源于同一主体操控,也可能源于委托同一代写服务,需结合其他维度综合判断",
  "llm_explanation": null,
  "skip_reason": null,
  "participating_subdims": ["llm_l8_stage1", "llm_l8_stage2"]
}
```

#### Scenario: ENABLED=false 早返

- **WHEN** `STYLE_ENABLED=false`
- **THEN** Agent 早返,evidence.enabled = false,不调 sampler / llm_client

#### Scenario: Stage1 失败整 Agent skip

- **WHEN** 3 bidder 中 1 bidder 的 Stage1 LLM 调用重试 2 次仍失败
- **THEN** AgentRunResult.score=0.0,evidence.skip_reason="L-8 Stage1 LLM 调用失败",summary 含 "语言风格分析不可用"

#### Scenario: Stage2 失败整 Agent skip

- **WHEN** Stage1 全部 3 bidder 成功,Stage2 LLM 调用重试 2 次仍失败
- **THEN** AgentRunResult.score=0.0,evidence.skip_reason="L-8 Stage2 LLM 调用失败"

### Requirement: style 环境变量

`style` MUST 暴露以下 env(关键参数严格校验,次要参数 warn fallback):

| env | 默认 | 类型 | 校验 |
|---|---|---|---|
| `STYLE_ENABLED` | true | bool | 任意 |
| `STYLE_GROUP_THRESHOLD` | 20 | int >= 2 | 严格,违反 raise |
| `STYLE_SAMPLE_PER_BIDDER` | 8 | int 5~10 | 严格(贴 spec L-8 5-10 段) |
| `STYLE_TFIDF_FILTER_RATIO` | 0.3 | float 0~1 | 宽松,越界 → warn fallback 0.3 |
| `STYLE_LLM_TIMEOUT_S` | 60 | int > 0 | 宽松 |
| `STYLE_LLM_MAX_RETRIES` | 2 | int >= 0 | 宽松 |

#### Scenario: 关键 env 非法 raise

- **WHEN** `STYLE_SAMPLE_PER_BIDDER=20`
- **THEN** `StyleConfig.from_env()` 抛 ValueError(超 5~10 范围)

#### Scenario: 次要 env 越界 warn fallback

- **WHEN** `STYLE_TFIDF_FILTER_RATIO=2.5`
- **THEN** logger.warning 记录;config.tfidf_filter_ratio = 0.3

### Requirement: _preflight_helpers.bidder_has_identity_info 新增

`backend/app/services/detect/agents/_preflight_helpers.py` MUST 新增:

```python
def bidder_has_identity_info(bidder) -> bool:
    """检查 bidder.identity_info 字段非空且 dict 非空。"""
    info = bidder.identity_info
    if info is None:
        return False
    if not isinstance(info, dict):
        return False
    return bool(info)  # 空 dict 返 False
```

`error_consistency.preflight` MUST 调此 helper 判断每个 bidder 的 identity_info 状态:全部缺 → downgrade;部分缺 → ok(downgrade 在 run 内部按 bidder 分别决策);全部有 → ok。

#### Scenario: identity_info 字段为空 dict 返 False

- **WHEN** bidder.identity_info = `{}`
- **THEN** `bidder_has_identity_info(bidder)` 返 False

#### Scenario: identity_info 字段为 None 返 False

- **WHEN** bidder.identity_info = None
- **THEN** `bidder_has_identity_info(bidder)` 返 False

#### Scenario: identity_info 含值返 True

- **WHEN** bidder.identity_info = `{"company_name": "甲建设"}`
- **THEN** `bidder_has_identity_info(bidder)` 返 True

### Requirement: llm_mock.py 扩展 L-5 + L-8 两阶段 fixture

`backend/tests/fixtures/llm_mock.py` MUST 扩展支持 L-5(error_consistency)+ L-8 两阶段(style):

1. **L-5 mock**:
   - `MOCK_L5_RESPONSES: dict[str, dict]` — key 由 `(bidder_a_id, bidder_b_id, segments_hash)` 派生;value 为 LLMJudgment dict
   - `mock_call_llm_l5(segments, bidder_a, bidder_b, *, simulate_failure: bool = False) -> LLMJudgment`
   - `simulate_failure=True` 抛 `LLMCallError("simulated failure")` 触发兜底测试

2. **L-8 Stage1 mock**:
   - `MOCK_L8_STAGE1_RESPONSES: dict[int, StyleFeatureBrief]` — key 为 bidder_id
   - `mock_call_l8_stage1(bidder_id, sampled_paragraphs, *, simulate_failure: bool = False) -> StyleFeatureBrief`

3. **L-8 Stage2 mock**:
   - `MOCK_L8_STAGE2_RESPONSES: dict[str, GlobalComparison]` — key 由 sorted bidder_id tuple 派生
   - `mock_call_l8_stage2(briefs, *, simulate_failure: bool = False) -> GlobalComparison`

4. **monkeypatch 注入约定**:测试通过 `monkeypatch.setattr(llm_judge, "call_l5", mock_call_llm_l5)` 等方式替换实际调用;production 走真实 LLM provider

5. **fixture 文件保持单一入口**:贴 CLAUDE.md "8 个 LLM 调用点共享" 约定;不在 production 代码中分散 mock 逻辑

#### Scenario: L-5 mock 返铁证响应

- **WHEN** 测试 setup MOCK_L5_RESPONSES 含特定 key;test 调 `mock_call_llm_l5(segments, ...)` 传匹配输入
- **THEN** 返预设的 `{"is_cross_contamination": true, "direct_evidence": true, ...}` LLMJudgment

#### Scenario: simulate_failure 触发兜底测试

- **WHEN** 测试调 `mock_call_l8_stage2(briefs, simulate_failure=True)`
- **THEN** 抛 `LLMCallError`;Agent 走 skip 哨兵路径

#### Scenario: 三 LLM 入口接口签名独立

- **WHEN** 测试代码同时 monkeypatch L-5 / L-8 stage1 / L-8 stage2
- **THEN** 三 mock 互不干扰;不同 Agent 的 LLM 测试隔离

### Requirement: L-9 摘要预聚合契约

`judge_llm.summarize(pair_comparisons, overall_analyses, per_dim_max, ironclad_info) -> dict` MUST 产生结构化摘要,喂给 L-9 LLM 的 input 必须走本契约,不得直喂 raw `evidence_json`(token 爆炸风险)。

摘要结构 MUST 包含:

```json
{
  "project": {"id": int, "name": str, "bidder_count": int},
  "formula": {"total": float, "level": "high|medium|low", "has_ironclad": bool},
  "dimensions": {
    "<dim_name>": {
      "max_score": float | null,
      "ironclad_count": int,
      "participating_bidders": [str, ...],
      "top_k_examples": [
        {"bidder_a": str, "bidder_b": str, "score": float, "evidence_brief": str}
      ],
      "skip_reason": str | null
    }
  }
}
```

规则:
- `dimensions` 字典 MUST 覆盖 11 维度(全部列出,哪怕 skip)
- `top_k_examples` 截断数由 env `LLM_JUDGE_SUMMARY_TOP_K`(default 3)控制,按 score 倒序
- **铁证 pair/OA 必须无条件列入 top_k_examples**(无论排名),`is_ironclad=true` 或 `evidence.has_iron_evidence=true` 标记
- `evidence_brief`:从 `evidence_json` 抽取关键字段拼接短字符串(≤ 200 字),不直塞整个 JSON
- global 型 Agent(error_consistency / style / image_reuse / price_anomaly):`top_k_examples` 填单行 OA 摘要(bidder_a/b 可为空或填"全局")
- `skip_reason`:`enabled=false` / `preflight failed` / `数据不足` 等,从 evidence_json 的 `skip_reason` 字段透出

token 目标:典型项目(5~10 bidder)摘要 3~8k token,大项目(20+ bidder)≤ 15k token。

#### Scenario: 铁证 pair 无条件入 top_k

- **WHEN** 11 个 pair 分数从高到低,铁证 pair 排第 7 位;top_k=3
- **THEN** 摘要 top_k_examples 列前 3 高分 pair,额外附加第 7 位铁证 pair(共 4 个),铁证标记

#### Scenario: skip 维度仍出现在摘要

- **WHEN** `image_reuse` Agent skip(数据不足),OverallAnalysis.evidence_json 含 `skip_reason`
- **THEN** 摘要 `dimensions.image_reuse` = `{max_score: null, skip_reason: "数据不足", top_k_examples: [], ...}`

#### Scenario: token 体量可控

- **WHEN** 项目 8 bidder × 11 维度 × C(8,2)=28 pair
- **THEN** 摘要 JSON.dumps 后 token 估算 ≤ 8k(非硬性 assert,靠 summary 结构约束)

---

### Requirement: L-9 LLM 调用契约

`judge_llm.call_llm_judge(summary: dict, formula_total: float) -> tuple[str | None, float | None]` MUST 满足以下契约:

- **输入**:`summary`(来自 `summarize`)+ `formula_total`(公式结论,供 LLM 作为"基础分"参考)
- **输出**:`(conclusion, suggested_total)` 成对返回
  - 成功:`(非空 str, 0~100 float)`
  - 失败:`(None, None)` — 调用方统一走降级分支
- **LLM 输出 Schema**(LLM 必须返回如下 JSON):
  ```json
  {
    "suggested_total": float,
    "conclusion": string,
    "reasoning": string
  }
  ```
- **失败判据**(返回 `(None, None)`):
  - 网络/API 错误 → 重试 `LLM_JUDGE_MAX_RETRY` 次,仍失败
  - 超时 `LLM_JUDGE_TIMEOUT_S` 秒 → 重试 / 失败
  - JSON 解析失败(含 `json.JSONDecodeError`)→ 消费重试名额
  - 缺必填字段 `suggested_total` 或 `conclusion` → 消费重试名额
  - `suggested_total` 超界([0, 100])→ 消费重试名额
  - `conclusion` 为空字符串 → 消费重试名额
- **重试策略**:失败后最多重试 `LLM_JUDGE_MAX_RETRY`(default 2)次,即最多调用 3 次;重试间隔 0(贴 C13 style_impl 风格)

#### Scenario: LLM 首次成功

- **WHEN** LLM 首次调用返回合法 JSON `{"suggested_total": 78.0, "conclusion": "三维度共振...", "reasoning": "..."}`
- **THEN** 返回 `("三维度共振...", 78.0)`,不触发重试

#### Scenario: LLM bad JSON 消费重试

- **WHEN** LLM 首次返回 `"not json"`,第二次返回合法 JSON
- **THEN** 第二次成功,返回合法结果;重试计数 +1(首次消费)

#### Scenario: LLM 重试耗尽

- **WHEN** LLM 连续 `MAX_RETRY+1=3` 次返回 bad JSON
- **THEN** 返回 `(None, None)`,调用方走降级

#### Scenario: LLM suggested_total 超界消费重试

- **WHEN** LLM 返回 `{"suggested_total": 120, "conclusion": "..."}`
- **THEN** 视为解析失败,消费重试;若重试耗尽返回 `(None, None)`

#### Scenario: LLM 超时

- **WHEN** LLM 调用超过 `LLM_JUDGE_TIMEOUT_S` 秒无响应
- **THEN** 视为单次调用失败,消费重试

---

### Requirement: L-9 可升不可降 clamp 契约

`judge.judge_and_create_report` MUST 按以下顺序 clamp LLM 建议分数:

1. `final_total = max(formula_total, llm_suggested_total)` — LLM 只能升分,不能降
2. `if has_ironclad: final_total = max(final_total, 85.0)` — 铁证硬下限守护
3. `final_total = min(final_total, 100.0)` — 天花板
4. `final_level = compute_level(final_total)`:≥70 `high` / 40-69 `medium` / <40 `low`

铁证硬下限由 `has_ironclad` 判定,逻辑与 `compute_report` 完全一致:
- 任一 `PairComparison.is_ironclad=true` 或
- 任一 `OverallAnalysis.evidence_json["has_iron_evidence"]=true`

LLM 若试图压低铁证分(建议 suggested_total < 85),clamp 步骤 2 将其无效化。

#### Scenario: LLM 升分跨档

- **WHEN** formula=65(medium)+ 无铁证 + LLM=75
- **THEN** final=75,level=high(跨档)

#### Scenario: LLM 建议低于公式被无效化

- **WHEN** formula=80 + 无铁证 + LLM=70
- **THEN** step1 max(80, 70)=80;final=80

#### Scenario: LLM 试图压铁证分被守护

- **WHEN** formula=88(有铁证)+ LLM=60
- **THEN** step1 max(88,60)=88;step2 铁证 max(88,85)=88;final=88

#### Scenario: LLM 建议与铁证一致

- **WHEN** formula=55 + 有铁证(升到 85)+ LLM=90
- **THEN** formula_total 已 85;step1 max(85, 90)=90;final=90

#### Scenario: 天花板守护

- **WHEN** formula=70 + LLM 意外返回 99.5
- **THEN** final=99.5(合法),不触发天花板

---

### Requirement: L-9 LLM 失败兜底模板契约

`judge_llm.fallback_conclusion(final_total: float, final_level: str, per_dim_max: dict, ironclad_dims: list[str]) -> str` MUST 产一段结构化中文模板字符串,满足:

- **前缀标语**:字符串 MUST 以 `"AI 综合研判暂不可用"` 开头(前端通过前缀 match 识别降级态加 banner)
- **模板内容**(顺序):
  1. 标语:`"AI 综合研判暂不可用,以下为规则公式结论:"`
  2. 总分与等级:`"本项目加权总分 {total} 分,风险等级 {level}。"`
  3. 铁证维度列表(若 `ironclad_dims` 非空):`"铁证维度:{dim1}、{dim2}(共 N 项)。"`;若空:跳过此句
  4. Top 3 高分维度:`"维度最高分:{dim1} {score1}、{dim2} {score2}、{dim3} {score3}。"`(若可用维度 < 3 则全列)
  5. 建议关注(铁证维度优先 + top 高分维度):`"建议关注:{dims}。"`

**约束**:
- 纯函数(无 IO,无副作用)
- 输入为 None / 空 dict 时不抛异常,模板对应字段降级(如 per_dim_max 为空 → 跳过 top3 句)
- `LLM_JUDGE_ENABLED=false` 时等价于 LLM 失败,调用此函数产降级文案

#### Scenario: 正常降级模板

- **WHEN** total=72.5, level="high", per_dim_max={"text_similarity":88, "error_consistency":92, "price_consistency":75, ...}, ironclad_dims=["error_consistency"]
- **THEN** 返回字符串以 `"AI 综合研判暂不可用"` 开头,包含 `"总分 72.5 分"`、`"风险等级 high"`、`"铁证维度:error_consistency"`、`"error_consistency 92"`, `"text_similarity 88"`, `"price_consistency 75"`

#### Scenario: 无铁证模板

- **WHEN** total=55, level="medium", ironclad_dims=[]
- **THEN** 字符串中不含"铁证维度"字样

#### Scenario: 空 per_dim_max 降级

- **WHEN** total=0, level="low", per_dim_max={}
- **THEN** 字符串以标语 + "总分 0 分,风险等级 low。" 结尾,不抛异常

#### Scenario: LLM_JUDGE_ENABLED=false 等价

- **WHEN** env `LLM_JUDGE_ENABLED=false`
- **THEN** judge 跳过 LLM 调用直接调 fallback_conclusion;llm_conclusion 前缀仍为 "AI 综合研判暂不可用"(对用户无感)

---

### Requirement: L-9 环境变量与配置

env 命名空间 `LLM_JUDGE_*`,`judge_llm.load_llm_judge_config() -> LLMJudgeConfig` MUST 读取并校验:

| env | 类型 | default | 语义 |
|---|---|---|---|
| `LLM_JUDGE_ENABLED` | bool | `true` | L-9 总开关;false → 跳过 LLM 直接走降级模板 |
| `LLM_JUDGE_TIMEOUT_S` | int | `30` | 单次 LLM 调用超时秒数 |
| `LLM_JUDGE_MAX_RETRY` | int | `2` | 失败重试次数(0=不重试,最多调用 MAX_RETRY+1 次) |
| `LLM_JUDGE_SUMMARY_TOP_K` | int | `3` | 每维度 top_k_examples 截断数 |
| `LLM_JUDGE_MODEL` | str | `""`(空=LLM 客户端默认) | 指定模型,贴现网 LLM 配置 |

校验规则(宽松风格,贴 C11/C12):
- bool 值非 `"true"/"false"` → fallback default + warn log
- int 非正 或 无法 parse → fallback default + warn log
- `TIMEOUT_S` 范围 `[1, 300]`,超界 fallback default
- `MAX_RETRY` 范围 `[0, 5]`,超界 fallback default
- `SUMMARY_TOP_K` 范围 `[1, 20]`,超界 fallback default

#### Scenario: 默认配置

- **WHEN** 未设任何 `LLM_JUDGE_*` env
- **THEN** config = `(enabled=true, timeout_s=30, max_retry=2, summary_top_k=3, model="")`

#### Scenario: 非法值 fallback

- **WHEN** `LLM_JUDGE_MAX_RETRY=abc` / `LLM_JUDGE_TIMEOUT_S=-1`
- **THEN** 两字段均 fallback 到 default(2 / 30),log warn

#### Scenario: enabled=false 关闭 LLM

- **WHEN** `LLM_JUDGE_ENABLED=false`
- **THEN** `judge_and_create_report` 跳过 LLM 调用,直接走降级分支

---

### Requirement: L-9 LLM mock 扩展

`backend/tests/fixtures/llm_mock.py` MUST 扩 L-9 相关 builder 和 fixture,作为测试单一入口:

- `make_l9_response(suggested_total: float, conclusion: str, reasoning: str = "") -> str` — 构造 L-9 合法 JSON 响应字符串
- `mock_llm_l9_ok(monkeypatch, suggested_total=78.0, conclusion="...")` — patch `call_llm_judge` 返回成功结果
- `mock_llm_l9_upgrade(monkeypatch, formula=65, llm=75)` — 升分跨档场景专用
- `mock_llm_l9_clamped(monkeypatch, formula=88, llm=60)` — LLM 试图降分被守护场景
- `mock_llm_l9_failed(monkeypatch)` — patch 返回 `(None, None)`
- `mock_llm_l9_bad_json(monkeypatch)` — patch LLM 客户端返回 bad JSON(触发解析失败+重试)

**约束**:
- 所有 L-9 测试 MUST 通过 `llm_mock.py` 入口 mock,不得在 test 文件内手写 `monkeypatch.setattr`
- 既有 `test_detect_judge.py` 等 judge 相关 test 默认 patch `call_llm_judge` 返回 `(None, None)`(等价 LLM 失败,走降级分支,total/level 保持公式值,与原断言一致)

#### Scenario: 成功 fixture 可用

- **WHEN** 测试调 `mock_llm_l9_ok(monkeypatch, suggested_total=80, conclusion="...")` + 触发 judge_and_create_report
- **THEN** AnalysisReport.llm_conclusion="...";final_total=max(formula, 80)

#### Scenario: 失败 fixture 走降级

- **WHEN** 测试调 `mock_llm_l9_failed(monkeypatch)` + 触发 judge
- **THEN** llm_conclusion 以"AI 综合研判暂不可用"开头;total=formula_total

#### Scenario: bad json fixture 触发重试

- **WHEN** 测试调 `mock_llm_l9_bad_json(monkeypatch)` + 触发 judge
- **THEN** 内部 LLM 客户端被调用 MAX_RETRY+1 次;最终返回 (None, None) 走降级

---

### Requirement: L-9 judge_and_create_report LLM 集成实施

`backend/app/services/detect/judge.py` 的 `judge_and_create_report(project_id, version)` MUST 集成 L-9 LLM 流水线:

- 现有 `compute_report` 纯函数 **保留不变**,作为"基础分"单一事实源
- 在 `compute_report` 调用后 + INSERT `AnalysisReport` 前,插入 L-9 流水线:
  1. `summary = judge_llm.summarize(...)`
  2. 若 `LLM_JUDGE_ENABLED=true`:`conclusion, suggested = judge_llm.call_llm_judge(summary, formula_total)`
  3. 若 LLM 成功:按 `L-9 可升不可降 clamp 契约` 计算 final_total/final_level;llm_conclusion = conclusion
  4. 若 LLM 失败 / disabled:final_total = formula_total;final_level = formula_level;llm_conclusion = `judge_llm.fallback_conclusion(...)`
- 幂等保证不变:`(project_id, version)` 已有 AnalysisReport → 早返

`judge_llm.py` 模块:
- 单文件 3 函数(`summarize` / `call_llm_judge` / `fallback_conclusion`)
- 不对外 `__all__` 导出(仅 judge.py 内部调用)
- algorithm version 登记:`llm_judge_v1`(记入 `backend/README.md`,不落 DB 字段)

#### Scenario: LLM 成功流水线

- **WHEN** 11 Agent 完成 + LLM mock ok + judge_and_create_report 触发
- **THEN** AnalysisReport 1 行落地;llm_conclusion = LLM conclusion;total/level = clamp 结果

#### Scenario: 幂等跳过

- **WHEN** 同 (project_id, version) 再次调 judge_and_create_report
- **THEN** 检测到已有 AnalysisReport,早返,不调 LLM

#### Scenario: compute_report 纯函数契约不变

- **WHEN** 既有 C6~C13 `test_compute_report_*` 测试运行
- **THEN** 全部通过,无需改动(契约向后兼容)

---

### Requirement: 模板簇识别(template cluster detection)

系统 SHALL 在 `judge.judge_and_create_report` 内、PC/OA 加载完成后、第一次 `_compute_dims_and_iron`(供 DEF-OA 写入)与 `_apply_template_adjustments` 调用之间执行模板簇识别,识别结果用于后续维度剔除与降权。识别动作不依赖 `compute_report`(production path 不调 `compute_report`,该函数仅作纯函数测试入口)。

识别规则:
1. 每个 bidder 收集其名下 `file_role in {"technical", "construction", "bid_letter", "company_intro", "authorization", "pricing", "unit_price"}` 的全部 BidDocument 对应的 DocumentMetadata 行;`file_role` 枚举值与 `parser/llm/role_classifier.py::VALID_ROLES` 对齐;**排除** `qualification`(PDF 营业执照等 author 常为"Admin"通用值噪音)+ `other`(无效分类)
2. 对每个 DocumentMetadata,构造 cluster_key = `(nfkc_casefold_strip(author), doc_created_at_utc_truncated_to_second)`;`nfkc_casefold_strip` 复用 `app.services.detect.agents.metadata_impl.normalizer.nfkc_casefold_strip`(NFKC 全角→半角 + casefold 大小写归一 + strip 两端空白),与 `metadata_author` agent 内部 author 比较语义对齐(防全角/大小写差异下 agent 判同 + iron=true 但 cluster 不命中导致抑制失效);任一字段为 NULL/空 → 该文档跳过(不参与识别),记 WARNING 日志 `template_cluster: bidder=<id> doc=<id> key incomplete`
3. `doc_created_at` 归一化:`dt.astimezone(timezone.utc).replace(microsecond=0)`;naive datetime 视为 UTC 后再归一(防 aware/naive 混用时 `==` 比较失败)
4. Bidder `i` 的 key 集合 `S_i = {(author_norm, created_at_norm), ...}`
5. 两个 bidder `i, j` 满足 `S_i ∩ S_j ≠ ∅` → 判同簇
6. 簇是等价类(A-B 同簇 + B-C 同簇 → A-B-C 同簇,实施用 union-find,bidder 数 N≤20 规模 O(N²) 可接受)
7. 等价类需 **≥ 2 bidder** 才构成有效簇;1-bidder 单点不成簇
8. `hash_sha256` **不**参与 cluster_key(投标方改内容导致哈希易变,误识别率高)

识别函数签名:`_detect_template_cluster(bidder_metadata_map: dict[int, list[DocumentMetadata]]) -> list[TemplateCluster]`,纯函数,位于 `backend/app/services/detect/template_cluster.py`;`bidder_metadata_map` 由调用方按 file_role 过滤后传入,函数本身不查 DB。

**已知遗留缺陷(预存量,本 Req 不治)**:`metadata_*` agent 内部 `extract_bidder_metadata` 不按 file_role 过滤,会扫 qualification 等噪音;follow-up 处理。

**失败兜底**:metadata 查询异常或全 NULL → 返空 list + ERROR 日志;judge 流水线继续走原打分路径,不阻塞检测。

#### Scenario: 3 bidder 同 metadata 全命中簇

- **WHEN** project 3 个 bidder(A/B/C)各有一份技术标 docx(file_role=technical),DocumentMetadata 均为 `author="LP" + doc_created_at="2023-10-09 07:16:00+08:00"`(北京时间)
- **THEN** `_detect_template_cluster` 返回 1 个 cluster,`cluster.bidder_ids=[A, B, C]`,`cluster_key_sample={"author":"lp","created_at":"2023-10-08T23:16:00+00:00"}`(author 经 nfkc_casefold_strip 归一化为小写,created_at 归一化为 UTC)

#### Scenario: bidder 有多份文档集合相交判簇

- **WHEN** bidder A 有 2 份文档 metadata `[(LP, t1), (LP, t2)]`(技术标 + 投标函);bidder B 有 1 份 `[(LP, t1)]`
- **THEN** `S_A ∩ S_B = {(LP, t1)}` 非空 → A-B 同簇

#### Scenario: file_role=qualification 不参与

- **WHEN** bidder A 的技术标 metadata=(LP, t1),营业执照 PDF metadata=(Admin, t0);bidder B 的技术标 metadata=(Admin, t0),qualification metadata=(XYZ, t2)
- **THEN** A 只贡献 `{(LP, t1)}`(qualification 被过滤);B 只贡献 `{(Admin, t0)}`;两 bidder 的 S 不相交 → **不**判同簇。Admin/t0 虽然在 A 的 qualification 中出现但因 file_role 被过滤,不参与识别

#### Scenario: 2 bidder 同模板 + 1 bidder 独立

- **WHEN** 3 bidder,A/B 技术标 metadata=(LP, t1);C 技术标 metadata=(XYZ, t2)
- **THEN** 返回 1 cluster,bidder_ids=[A, B];C 不属于任何簇

#### Scenario: metadata author NULL → 该文档跳过

- **WHEN** bidder A 的所有 cluster 范围内文档 metadata.author 均为 NULL
- **THEN** A 的 `S_A` 为空;A 不参与任何簇识别;日志 WARNING `template_cluster: bidder=A all keys incomplete`;A 所有 pair 走原打分路径

#### Scenario: aware vs naive datetime 视为同一瞬间

- **WHEN** bidder A metadata.doc_created_at 为 `datetime(2023,10,9,7,16,0,tzinfo=UTC)`;bidder B 为 naive `datetime(2023,10,9,7,16,0)`(被视为 UTC)
- **THEN** 归一化后两值相等;若 author 也一致则判同簇

#### Scenario: 1 bidder 项目返空

- **WHEN** project 只有 1 个 bidder
- **THEN** `_detect_template_cluster` 返空 list(无法构成跨 bidder 等价类)

#### Scenario: 所有独立不成簇返空

- **WHEN** 所有 bidder 的 S 两两不相交
- **THEN** 返空 list

#### Scenario: 传递闭包合并

- **WHEN** A-B 同簇(共享 key1);B-C 同簇(共享 key2),但 A-C 无直接交集
- **THEN** union-find 合并为单簇 `bidder_ids=[A,B,C]`;cluster_key_sample 任选其一(如 key1 或 key2)

#### Scenario: metadata 查询异常不阻塞

- **WHEN** DB 查询 `document_metadata` 抛异常
- **THEN** `_detect_template_cluster` 返空 list + 写 ERROR 日志;judge 流水线继续

---

### Requirement: 模板簇维度剔除/降权与铁证抑制

识别出模板簇后,`judge.judge_and_create_report` MUST 调用 `_apply_template_adjustments(pcs, oas, clusters)` 构造 `(adjusted_pcs, adjusted_oas, adjustments)` 三元组并下发到 `_compute_dims_and_iron` / `_has_sufficient_evidence`(详见 MODIFIED "证据不足判定规则")/ `summarize`(经 `_run_l9` 透传)各 helper(均通过本 change 扩展的 keyword-only `adjusted_pcs / adjusted_oas` 可选参数消费),缺失回落 ORM 原值;adjustment 清单写入 `AnalysisReport.template_cluster_adjusted_scores`,**不回写 DB**(PC/OA 表行保留 agent 写入的原始 score / is_ironclad / evidence_json,符合审计原则)。

**`compute_report` 自身签名/语义保持不变**(主 spec L268 + L2843 既有契约保留);本 ADD Req 不修改主 spec L268 的 `compute_report` 契约(防 archive sync 时误改纯函数测试入口的签名)。

**剔除(adjusted_score=0 + is_ironclad 抑制)** 四维:

1. `structure_similarity` PairComparison:pair 两端 bidder 均在**同一个**簇 → adjusted_score=0.0,adjusted_is_ironclad=false,evidence_extras `{template_cluster_excluded: true, raw_score: <orig>, raw_is_ironclad: <orig>}`
2. `metadata_author` PC:同上(铁证源是模板 author=LP 不是围标;`metadata_impl/author_detector.py` 在 score≥85 时写 is_ironclad=true,抑制条款非空操作)
3. `metadata_time` PC:同上(`metadata_impl/time_detector.py` 在 created_at 完全相等时可能 score≥85 + is_ironclad=true;同一信号既识别污染又计分,必须抑制)
4. `style` OverallAnalysis(global):**全覆盖判定**(round 7 reviewer M4 锁产品语义)= `len(clusters)==1 and 该簇 bidder_ids == project 全部 bidder_ids`(单一簇覆盖全部 bidder)→ OA adjusted_score=0.0,evidence_extras `{template_cluster_excluded_all_members: true, raw_score: <orig>}`;否则(部分 bidder 在簇 / 多簇并存即使各簇都覆盖 / 单簇但只覆盖部分)→ **保留原分**(先期简化,N-gram 留 follow-up,见 R5);**注**:`style.py::_build_evidence` 不输出 `has_iron_evidence` 字段(本期 style 不写 iron),抑制 `has_iron_evidence` 实际为 no-op,但 evidence_extras 仍标 `excluded_all_members=true` 用于 observability

**降权(adjusted_score = raw × 0.5)** 一维 + 铁证豁免:

5. `text_similarity` PC:pair 两端同簇 → adjusted_score = `round(raw * 0.5, 2)`,evidence_extras `{template_cluster_downgraded: true, raw_score: <orig>}`
6. **铁证豁免**:若该 PC `is_ironclad=true`(`text_sim_impl/aggregator.py::compute_is_ironclad`:LLM 段级判定 plagiarism 段数 ≥3 或 plagiarism 占比 ≥50%,LLM 主动区分 template/plagiarism,iron=true 时即"模板外仍有大量真抄袭")→ **不降权保留原分**,evidence_extras `{template_cluster_downgrade_suppressed_by_ironclad: true, raw_score: <orig>}`,adjusted_is_ironclad 保持 true(is_ironclad 不被抑制,铁证独立有效)

**不受影响维度**(adjusted_score 沿用 raw + is_ironclad 沿用 raw):
- `section_similarity` / `metadata_machine` / `price_consistency` / `price_anomaly` / `image_reuse` / `error_consistency`(共 6 维;加上剔除 4 维 + 降权 1 维 = 11 维全覆盖)
- 各维度 is_ironclad/has_iron_evidence 写入事实(影响 fixture 真实性):
  - PC.is_ironclad 由以下 agent 写:`metadata_author` / `metadata_time` / `metadata_machine` / `text_similarity`(LLM plagiarism)/ `section_similarity` / `structure_similarity` / `price_consistency`
  - OA.evidence_json.has_iron_evidence 由 `error_consistency` + DEF-OA 聚合行(从 PC.is_ironclad 聚合)写
  - **`image_reuse` 与 `style` 本期不写 iron**(`image_reuse.py:9` "is_iron_evidence 始终 False" + `style.py::_build_evidence` 无 has_iron_evidence)— 涉及这两个 agent 的 fixture 不能假设原 iron=true

铁证字段总体原则:
- 剔除的 4 维:`is_ironclad` / `has_iron_evidence` 必须抑制为 false(铁证源是模板固有,不是围标信号)
- 降权的 text_similarity:`is_ironclad` 若原为 true 则保持 true 且降权豁免
- 不受影响维度:沿用 raw 不动

**可观测性记录**:每条 adjustment 写入 `AnalysisReport.template_cluster_adjusted_scores.adjustments` 数组,统一 shape 含 `scope` 字段区分三类 entry:

```json
{
  "scope": "pc" | "global_oa" | "def_oa",
  "pair": [bidder_id_1, bidder_id_2] | null,    // scope="pc" 时必填,其他场合 null
  "oa_id": <int> | null,                          // scope="global_oa" / "def_oa" 时必填,scope="pc" 时 null
  "dimension": "<dim_name>",
  "raw_score": <float>,
  "adjusted_score": <float>,
  "raw_is_ironclad": <bool> | null,               // PC 维度填 bool;global_oa(style)/ def_oa 无此字段填 null
  "raw_has_iron_evidence": <bool> | null,         // OA 维度填 bool;PC 维度填 null
  "reason": "template_cluster_excluded" | "template_cluster_downgraded" | "template_cluster_excluded_all_members" | "template_cluster_downgrade_suppressed_by_ironclad" | "def_oa_aggregation_after_template_exclusion"
}
```

scope 语义:
- `"pc"` — PairComparison 行的 adjustment(structure_similarity / metadata_author / metadata_time / text_similarity 受污染 pair)
- `"global_oa"` — 原生 global agent OA 行的 adjustment(本 change 仅 style 在全覆盖时进入此类)
- `"def_oa"` — 受污染维度的 DEF-OA aggregation OA 行的 adjustment(score=`max(adjusted PC scores)`,has_iron_evidence=`any(adjusted PC.is_ironclad)`)

总 entry 数 = scope=pc 数 + scope=global_oa 数 + scope=def_oa 数。例:3 bidder 全簇 prod fixture → 12 个 pc(structure×3 + metadata_author×3 + metadata_time×3 + text×3)+ 1 个 global_oa(style)+ 4 个 def_oa(structure / metadata_author / metadata_time / text 各 1)= **17 条**。

`AnalysisReport.template_cluster_detected = (len(adjustments) > 0)`,BOOLEAN NOT NULL DEFAULT FALSE。

**adjusted dict 数据契约**(具体调用顺序与 helper 实施手法见 design.md D5 / D7):
- `AdjustedPCs = dict[int, dict]`(key = pc.id)+ `AdjustedOAs = dict[int, dict]`(key = oa.id)拆开,避免两表 PK 取值重叠错位
- `_apply_template_adjustments` MUST 同时为受污染维度的 PC.id **与** DEF-OA OA.id 产 entry;DEF-OA entry 中 `score = max(全集 adjusted-or-raw PC scores)`,`has_iron_evidence = any(全集 adjusted-or-raw PC.is_ironclad)`(全集含 in-cluster 受调整 + out-of-cluster 沿用 raw + 铁证豁免保留 raw 三类 PC)
- `_apply_template_adjustments` 区分 DEF-OA vs 原生 global OA 按 `oa.dimension in PAIR_DIMENSIONS`:in → `scope="def_oa"`;out → `scope="global_oa"`(本 change 仅 style 进入此类)

**关键 invariant**(实施期 MUST 保证):
1. **raw 入库 / adjusted 算分**:DB 中 PC/OA 行的 score / is_ironclad / evidence_json 保留 agent 写入的原始值(D7 审计要求);`_compute_formula_total / _has_sufficient_evidence / summarize` 等下游消费的是 adjusted dict + raw 回落的组合
2. **`compute_report` 签名/语义保持不变**(主 spec L268 + L2843 既有契约 + 现有 L1 signature_unchanged 测试);本 ADD Req 不修改主 spec L268 的 `compute_report` 契约
3. **无 cluster 命中(`adjustments==[]`)行为完全等价 change 前**:helper 全部传 None,走原 AgentTask 分母 + raw per_dim_max
4. **DEF-OA local list 同步**:DEF-OA 写入步骤 `session.add(oa)` 后 MUST 同步 `overall_analyses.append(oa)`;调用 `_has_sufficient_evidence` 时 list 长度 == 11(4 global + 7 pair)

#### Scenario: 3 bidder 全在同簇 → structure pair 全剔 + is_ironclad 抑制

- **WHEN** 3 bidder 全在同簇;structure_similarity 产出 3 对 PC(A-B=100 iron=true, A-C=100 iron=true, B-C=100 iron=true)— 与 prod 真实形态对齐(`structure_sim_impl/scorer.py:74-77` 在 max_sub≥0.9 且 score≥85 时写 iron=true);DEF-OA structure_similarity 写入 `score=100, has_iron_evidence=true`(从 raw PC 聚合)
- **THEN** 3 条 PC adjustment + 1 条 DEF-OA OA adjustment 记录写入;`adjusted_pcs[pc.id]={"score":0, "is_ironclad":false, "evidence_extras":{"raw_score":100, "raw_is_ironclad":true, "template_cluster_excluded":true}}` × 3;`adjusted_oas[def_oa.id]={"score":0, "has_iron_evidence":false, "evidence_extras":{"raw_score":100, "raw_has_iron_evidence":true}}`;helper 读到 `per_dim_max["structure_similarity"]=0`,iron 集合不含 structure_similarity

#### Scenario: metadata_author 带铁证被剔且抑制

- **WHEN** 3 bidder 全在同簇;metadata_author 产出 3 对 PC 均 score=100 + is_ironclad=true(`metadata_impl/author_detector.py` 阈值 85 触发)
- **THEN** adjusted_score=0 + adjusted is_ironclad=false(**全部**被抑制);adjustment.raw_is_ironclad=true 写入 JSONB 供审计;`_compute_dims_and_iron` 扫到的 is_ironclad=false;`has_ironclad=False`(其他维若也被抑制);`_compute_formula_total` 不触发 `max(total, 85.0)`;`_has_sufficient_evidence` 铁证短路不命中

#### Scenario: metadata_time 带铁证被剔且抑制

- **WHEN** 3 bidder 全在同簇;metadata_time PC 因 created_at 完全相同 sub_score=1.0 + agent 层面 is_ironclad=true
- **THEN** adjusted_score=0 + adjusted is_ironclad=false;adjustment 记录 raw_is_ironclad=true

#### Scenario: style 全覆盖 → OA 剔除

- **WHEN** 3 bidder 全在某一簇,style OA score=76.5(style 不写 has_iron_evidence)
- **THEN** adjusted_score=0;adjustment `{pair:null, dimension:"style", raw_score:76.5, raw_is_ironclad:false, reason:"template_cluster_excluded_all_members"}`

#### Scenario: style 部分覆盖 → 保留原分(先期简化)

- **WHEN** 3 bidder,A/B 在簇,C 独立;style OA score=80
- **THEN** adjusted_score=80(保持);无 style adjustment 记录

#### Scenario: text_sim 降权 ×0.5 无铁证

- **WHEN** A-B 在同簇,text_similarity PC A-B raw=91.59 is_ironclad=false
- **THEN** adjusted_score=45.80(`round(91.59 * 0.5, 2)`);adjustment.reason="template_cluster_downgraded"

#### Scenario: text_sim 有铁证触发降权豁免

- **WHEN** A-B 在同簇,text_similarity PC A-B raw=95.0 is_ironclad=true(LLM 段级判定 ≥3 段或 ≥50% plagiarism,而非 template)
- **THEN** adjusted_score=95.0(**不**降权);adjusted is_ironclad=true 保留;adjustment.reason="template_cluster_downgrade_suppressed_by_ironclad";真围标铁证路径正常生效

#### Scenario: 不受影响维度不调整

- **WHEN** A-B 在同簇,section_similarity PC=70 iron=false / metadata_machine PC=30 iron=false / price_consistency PC=50 iron=false / price_anomaly OA=20 / image_reuse OA=88(本期不写 iron)/ error_consistency OA=40 has_iron_evidence=false
- **THEN** 5 条 PC/OA 的 adjusted_score 均沿用 raw,is_ironclad/has_iron_evidence 沿用 raw;无 adjustment 记录

#### Scenario: 真围标 + 同模板 → text_sim 铁证豁免 + 独立铁证维度保留 → 仍能判 high

- **WHEN** 3 bidder 全在同簇(metadata 污染);text_similarity PC A-B raw=95 is_ironclad=true(LLM plagiarism ≥3 段;模板外仍有大量抄袭);section_similarity PC A-B=85 iron=true(章节内容碰撞);error_consistency OA has_iron_evidence=true
- **THEN** text_sim 降权豁免保留 95 + iron=true;section_similarity 不受影响保留 85 + iron=true;error_consistency 不受影响保留 has_iron_evidence=true;`has_ironclad=True`(多维铁证);`formula_total≥85`;`risk_level=high`;真围标铁证链完整保留,模板排除不掩盖真信号

#### Scenario: adjustment 不回写 DB

- **WHEN** adjustment 对 PC A-B.structure_similarity 产出 adjusted_score=0
- **THEN** DB 中 `pair_comparisons` 行的 `score` 字段保持原值 100(agent 写入值);`analysis_report.template_cluster_adjusted_scores.adjustments` JSONB 记录 raw=100 adjusted=0;重跑 judge 读 DB 原值后再次应用 adjustment,结果幂等

#### Scenario: template_cluster_detected 仅在有真实簇时 true

- **WHEN** 模板簇识别返回非空 cluster 列表且产生 ≥1 条 adjustment
- **THEN** `AnalysisReport.template_cluster_detected=true`
- **WHEN** 模板簇识别返空 list(所有 bidder metadata 独立或 NULL)
- **THEN** `template_cluster_detected=false` + `template_cluster_adjusted_scores=null`

#### Scenario: 无 cluster 命中走老路径(invariant 3)

- **WHEN** `_detect_template_cluster` 返空 list(metadata 全 NULL 或两两不相交)
- **THEN** 后续 helper 全部传 None;`_has_sufficient_evidence` 走 AgentTask 分母;行为与 change 前完全等价(不引入任何回归)

### Requirement: 报价超限识别 (price_overshoot)

系统 SHALL 提供 global 型检测维度 `price_overshoot`:消费 `BidderPriceSummary.total_price`(由既有 `anomaly_impl/extractor.aggregate_bidder_totals` 产出)与 `Project.max_price`,任一 bidder 的 `total_price` 严格大于 `max_price` SHALL 视为铁证级信号(`evidence["has_iron_evidence"]=True; score=100`),由既有 judge 铁证短路逻辑升 high 风险等级。

`max_price` 为 `NULL` 或 `≤0` 时,该 Agent SHALL preflight skip,写一行 OverallAnalysis 占位 `evidence{enabled: false, reason: "未设限价"}`(对齐既有 "所有 4 global agent 必须写恰好一行 OA" 约定;新加该 Agent 后改为"所有 5 global agent")。

evidence schema:`overshoot_bidders: list[{bidder_id: int, total: Decimal, ratio: float}]`,ratio = `(total - max_price) / max_price`,前端依此渲染 `Alert type="error"` + 客观陈述文案。

#### Scenario: 任一 bidder 超限触发铁证
- **WHEN** project.max_price=400 且某 bidder.total_price=500(超 25%)
- **THEN** Agent run() 写 OverallAnalysis 行 `evidence={"has_iron_evidence": true, "overshoot_bidders": [{"bidder_id": ..., "total": 500, "ratio": 0.25}]}; score=100`;judge 铁证短路升 risk_level=high

#### Scenario: 未设限价或限价为零跳过
- **WHEN** project.max_price 为 NULL 或 ≤0
- **THEN** preflight skip;写 OA 行 `evidence={"enabled": false, "reason": "未设限价"}; score=0`;judge 不升 high(无信号)

### Requirement: 报价总额完全相等识别 (price_total_match)

系统 SHALL 提供 global 型检测维度 `price_total_match`:消费 `BidderPriceSummary.total_price`,遍历两两 bidder pair,任一 pair 的 `total_price` 完全相等(Decimal 严格相等比较)SHALL 视为铁证级信号,由既有 judge 铁证短路逻辑升 high。

任一 bidder `parse_status` 非 `priced` 或 `total_price=NULL` 时,该 Agent SHALL preflight skip,写 OA 行 `evidence{enabled: false, reason: "数据缺失"}`。

evidence schema:`pairs: list[{bidder_a_id: int, bidder_b_id: int, total: Decimal}]`,前端依此渲染维度行 `Tag color="error"` 文字"两家总价完全相同"。

与既有 `price_consistency`(pair / 行级 4 子检测)责任划分:price_consistency 看行级模式(尾数 / 单价匹配 / 系列关系),price_total_match 看 bidder 汇总值;两 detector 在"行也相同 total 也相同"场景同时命中是合理的(双重铁证),UI 各自维度独立显示不冲突。

跨币种场景(单 project 多 currency)为 known limitation,本 Requirement 不处理;follow-up change 加 currency 一致性 preflight。

#### Scenario: 两家 bidder 总价完全相等触发铁证
- **WHEN** 两家 bidder.total_price 都为 Decimal("486000.00"),即使 PriceItem 行级数据不同(品类 / 数量 / 单价错配)
- **THEN** Agent run() 写 OA 行 `evidence={"has_iron_evidence": true, "pairs": [{"bidder_a_id": ..., "bidder_b_id": ..., "total": "486000.00"}]}; score=100`;judge 铁证短路升 risk_level=high

#### Scenario: 任一 bidder 数据缺失跳过
- **WHEN** 某 bidder.parse_status="price_partial" 或 BidderPriceSummary.total_price=NULL
- **THEN** preflight skip;写 OA 行 `evidence={"enabled": false, "reason": "数据缺失"}; score=0`;judge 不升 high

