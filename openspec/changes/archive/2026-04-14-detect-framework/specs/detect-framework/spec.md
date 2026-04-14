## ADDED Requirements

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

系统启动后 `AGENT_REGISTRY` MUST 恰好含 10 条目,name 为:
- pair 型 7 个:`text_similarity / section_similarity / structure_similarity / metadata_author / metadata_time / metadata_machine / price_consistency`
- global 型 3 个:`error_consistency / style / image_reuse`

C6 阶段所有 10 Agent 的 `run()` 为 dummy(sleep 0.2~1.0s 随机时长 + 返 0~100 随机分 + "dummy result" summary)。C7~C13 各 change 替换对应 Agent 的 `run()`,不改注册表 key 和签名。

#### Scenario: 注册表含 10 Agent

- **WHEN** 加载 `app.services.detect.agents.*` 模块后读 `AGENT_REGISTRY`
- **THEN** 恰好 10 条目,7 pair + 3 global 分类正确

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

所有 AgentTask 进终态(succeeded/failed/timeout/skipped)后,系统 MUST 调 `judge.compute_report(project_id, version)`:
1. 加载该 version 所有 PairComparison + OverallAnalysis 行
2. 每维度取跨 pair/global 最高分 `per_dim_max[dim] = max(all scores for dim)`
3. `total_score = sum(per_dim_max[dim] * DIMENSION_WEIGHTS[dim] for dim in 10 维度)`,四舍五入 2 位
4. 若 `any(pc.is_ironclad for pc in pair_comparisons)` → `total_score = max(total_score, 85.0)`(铁证强制至少 high)
5. `risk_level`:total_score ≥ 70 → `high`;40-69 → `medium`;< 40 → `low`
6. INSERT AnalysisReport `{project_id, version, total_score, risk_level, llm_conclusion=''}`(`llm_conclusion` 留空,C14 补)
7. UPDATE project.status = `completed`
8. broker publish `report_ready` 事件

权重 `DIMENSION_WEIGHTS` 合计 = 1.00,占位值见 design.md D4。

#### Scenario: 全 succeeded 走完整公式

- **WHEN** 24 AgentTask 均 succeeded,各随机分
- **THEN** AnalysisReport 1 行落地,total_score / risk_level 按公式计算;project.status='completed'

#### Scenario: 部分 skipped / failed 仍出报告

- **WHEN** 24 AgentTask 中 10 个 succeeded,8 个 skipped,4 个 failed,2 个 timeout
- **THEN** AnalysisReport 仍生成;缺失维度 per_dim_max=0,total_score 按可用维度计算

#### Scenario: 全 skipped 的极端情况

- **WHEN** 所有 AgentTask 均 skipped(如所有 bidder 文件都缺失)
- **THEN** AnalysisReport 生成,total_score=0, risk_level='low';summary 标 "数据不足"

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
  "agent_tasks": [
    {"id", "agent_name", "agent_type", "pair_bidder_a_id", "pair_bidder_b_id",
     "status", "started_at", "finished_at", "elapsed_ms", "score", "summary", "error"}
  ]
}
```

项目从未启动检测(无 AgentTask)→ 返 `{"version": null, "project_status": <current>, "agent_tasks": []}` 200(非 404,便于前端幂等拉取)。

#### Scenario: 检测中查看快照

- **WHEN** 检测进行中 → `GET /api/projects/{pid}/analysis/status`
- **THEN** 响应 200,`agent_tasks` 列表含所有 24 条,status 混合 `running / pending / succeeded`

#### Scenario: 从未检测过返空

- **WHEN** 新建项目(无 AgentTask)→ 查询
- **THEN** 响应 200 + `{"version": null, "project_status": "draft", "agent_tasks": []}`

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

后端 MUST 在 `app/services/detect/agents/` 下提供 10 个文件,每个文件定义一个 Agent 骨架,通过 `@register_agent` 装饰器注册到 AGENT_REGISTRY。

每个骨架文件 MUST 含:
- `preflight` 函数(按 "Agent preflight 前置条件自检" Requirement 规则)
- `run(ctx: AgentContext) -> AgentRunResult` 函数,C6 内实现为 dummy:
  - `await asyncio.sleep(random.uniform(0.2, 1.0))`
  - `score = random.uniform(0, 100)`
  - `summary = f"dummy {name} result"`
  - pair 型:INSERT PairComparison 行(随机 is_ironclad 但权重 < 10%)
  - global 型:INSERT OverallAnalysis 行
  - 返 `AgentRunResult(score=score, summary=summary)`

`AgentRunResult` 是 namedtuple,字段:`score: float, summary: str, evidence_json: dict = {}`。

C7~C13 各 change 替换对应 `run()` 实现,不改 preflight、不改文件名、不改注册 key。

#### Scenario: 10 Agent 模块加载后注册表完整

- **WHEN** `from app.services.detect import agents` 触发所有 agents 模块加载
- **THEN** `AGENT_REGISTRY` 含 10 条目;每条 `run` 可调

#### Scenario: dummy run 产生 PairComparison 行

- **WHEN** 调 text_similarity dummy run(pair 型)
- **THEN** pair_comparisons 表新增 1 行,score 在 0~100;summary 含 "dummy"

#### Scenario: dummy run 产生 OverallAnalysis 行

- **WHEN** 调 style dummy run(global 型)
- **THEN** overall_analyses 表新增 1 行

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
