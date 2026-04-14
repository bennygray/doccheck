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

C10 归档后,Agent `text_similarity`(C7)、`section_similarity`(C8)、`structure_similarity`(C9)、`metadata_author` / `metadata_time` / `metadata_machine`(C10)的 `run()` 已替换为真实算法,不再走 dummy;其余 4 个 Agent(`price_consistency / error_consistency / style / image_reuse`)`run()` 继续走 dummy,直至 C11~C13 各自替换。

每个尚未替换为真实实现的骨架文件 MUST 含:
- `preflight` 函数(按 "Agent preflight 前置条件自检" Requirement 规则)
- `run(ctx: AgentContext) -> AgentRunResult` 函数,dummy 实现:
  - `await asyncio.sleep(random.uniform(0.2, 1.0))`
  - `score = random.uniform(0, 100)`
  - `summary = f"dummy {name} result"`
  - pair 型:INSERT PairComparison 行(随机 is_ironclad 但权重 < 10%)
  - global 型:INSERT OverallAnalysis 行
  - 返 `AgentRunResult(score=score, summary=summary)`

`AgentRunResult` 是 namedtuple,字段:`score: float, summary: str, evidence_json: dict = {}`。当整 Agent 因数据缺失 run 级 skip 时 `score=0.0` 作为哨兵值,evidence 层通过 `participating_fields=[]`(或 `participating_dimensions=[]`,按 Agent 定义)标记。

C11~C13 各 change 替换对应 `run()` 实现,不改 preflight、不改文件名、不改注册 key。

#### Scenario: 10 Agent 模块加载后注册表完整

- **WHEN** `from app.services.detect import agents` 触发所有 agents 模块加载
- **THEN** `AGENT_REGISTRY` 含 10 条目;每条 `run` 可调

#### Scenario: dummy run 产生 PairComparison 行

- **WHEN** 调 price_consistency dummy run(pair 型,C10 后 dummy 列表的一员)
- **THEN** pair_comparisons 表新增 1 行,score 在 0~100;summary 含 "dummy"

#### Scenario: dummy run 产生 OverallAnalysis 行

- **WHEN** 调 style dummy run(global 型)
- **THEN** overall_analyses 表新增 1 行

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

---

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
