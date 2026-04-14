## Context

### 现状(C5 归档后)

- 后端解析流水线已通:extract(C4)→ content(C5)→ role classify(C5)→ price rule detect(C5)→ price fill(C5);bidder 进 `identified / priced / price_partial / identify_failed / price_failed` 等终态后停在原地
- `projects.status` 枚举已含 `analyzing`(C3 预留),但无业务逻辑触发
- `app/api/routes/analysis.py` / `reports.py` 不存在(C1 占位也没给)
- `progress_broker`(C5)是单进程内存 broker,已支持 `subscribe / publish / unsubscribe`;C6 只扩事件 schema
- Agent 表、PairComparison、OverallAnalysis、AnalysisReport 均未建
- LLM 适配层 `app/services/llm/`(C1)+ `ScriptedLLMProvider`(C5 扩)可直接复用,但 C6 不调 LLM(综合研判留 C14)
- `clean_users` fixture 清 8 张表(users / projects / 4 张 C4 表 + 4 张 C5 表),C6 引 5 张新表需扩
- C4/C5 遗留:`extract / content_parse / llm_classify` 3 阶段协程 event loop 重启丢任务(报价规则那一半 C5 的 E3 DB 原子占位已消化)

### 约束

- **单进程内存 broker**:C6 继续延用 C5 决策,broker 不上 Redis;重启丢订阅(SSE 客户端自动重连走 `/analysis/status` 恢复)
- **不引新库**:asyncio + SQLAlchemy + 复用 C5 progress_broker + LLM 适配层,无 `celery / dramatiq / arq / pulsar` 等
- **ProcessPoolExecutor 从 C1 迁入**:user prompt 明确要求;但 C6 dummy Agent 不走 pool(无 CPU 密集),只保留接口 hook 给 C7~C13 消费
- **L3 Docker 依赖**:Docker Desktop kernel-lock 持续影响 `docker compose up` 真实部署;沿用 C5 L3 降级手工凭证策略

### 干系方

- **审查员(用户)**:前端点击"启动检测" → 看进度 → 查看报告骨架
- **后端维护者(后续 change 实施者)**:C7~C13 只改 Agent 模块,不 touch 框架
- **运维/DBA**:alembic 0005 迁移、async_tasks 表扫描性能

## Goals / Non-Goals

### Goals

1. **启动检测 API** 完整落地:前置校验 + AgentTask 批量创建 + 异步调度;analyzing 态 409 幂等
2. **10 Agent 注册表 + 自检骨架**:name / agent_type / preflight 三元组为稳定 contract;C7~C13 只填 `run()`
3. **Agent 并行调度**:asyncio.gather + return_exceptions;单 Agent 5min + 全局 30min 超时;单失败隔离
4. **SSE 进度推送**:复用 progress_broker,推 `agent_status / report_ready / heartbeat`
5. **综合研判占位**:按 requirements §F-RP-01 加权求和 → total_score + risk_level;AnalysisReport 行落地 = 检测完成信号
6. **通用任务表**:`async_tasks` 覆盖 4 subtype,启动 scan → stuck 任务标 timeout + 实体状态回滚(D3 决策)
7. **报告页 Tab1 骨架**:总分 + 等级 + 10 维度得分列表;Tab2~4 留 C14
8. **测试分层**:L1 单元 + L2 e2e API;L3 Playwright 优先跑,失败降级手工凭证

### Non-Goals

- **真实 Agent 实现**:10 Agent 的 `run()` 全部走 dummy(sleep + 随机 0~100 分),真实逻辑留 C7~C13
- **LLM 综合研判**:C6 不调 LLM;`llm_conclusion` 字段留空 + 标 "AI 研判暂不可用",C14 接入真实 LLM
- **报告页完整 4 Tab**:概要 / 对比详情 / 维度分析 / 检测日志 4 个 Tab 只做 Tab1;Tab2~4 的热力图 / 雷达图 / ECharts / Markdown 渲染全部留 C14
- **ProcessPoolExecutor 真实消费**:框架预留 `run_in_executor` hook,C7 首个 CPU 密集 Agent 再用;C6 不强制任何 Agent 走 pool
- **Agent 任务表自动恢复重调**:D3 明确只扫不自动恢复,用户手动重试(已有 `POST /documents/{id}/re-parse` + 新 `POST /analysis/start` 支撑)
- **跨进程锁 / Redis / 分布式任务队列**:单进程内存 broker 延续
- **报价解析批量应用失败 LLM 重试**:US-5.4 AC-5 描述的"失败的投标人单独调用 LLM 重新理解表结构"在 C5 已由人工修正端点(`PUT /price-rules/{id}`)覆盖;C6 不重复做

## Decisions

### D1 — async_tasks 通用表 schema 与 subtype 枚举

**决策**:单表 `async_tasks`,`subtype` 字段区分 4 类异步任务,而非每类一张表。

| subtype | entity_type | entity_id | 产生时机 | 恢复策略(scanner 扫到 stuck) |
|---|---|---|---|---|
| `extract` | bidder | bidder_id | C4 `extract/engine.py` 解压协程启动 | bidder.parse_status: `extracting → failed` |
| `content_parse` | bid_document | doc_id | C5 `parser/content/__init__.py` 每文档提取 | bid_document.parse_status: `identifying → identify_failed`;聚合影响 bidder.parse_status |
| `llm_classify` | bidder | bidder_id | C5 `parser/llm/role_classifier.py` 分类协程 | bidder.parse_status: `identifying → identify_failed` |
| `agent_run` | agent_task | agent_task_id | C6 engine orchestrator 启动单 Agent | agent_tasks.status: `running → timeout`;全 Agent 都恢复后项目 `analyzing → ready`(若已有 AgentTask 全部 terminate)|

字段:`id / subtype VARCHAR(32) / entity_type VARCHAR(32) / entity_id INTEGER / status VARCHAR(16) / started_at / heartbeat_at / finished_at / error TEXT / created_at`;索引 `(status, heartbeat_at)` 支撑扫描。

**替代方案**:
- 每 subtype 一张表 → 4 张表重复字段,scanner 需 union,拒绝
- 加 JSON 字段装 context → 不利于索引,拒绝
- 直接在业务表(bidders / agent_tasks)加 `heartbeat_at` → 耦合业务状态与任务心跳,C4/C5 业务表已有 parse_status,再加 heartbeat 语义重叠,拒绝

**理由**:subtype 固定 4 类,单表 + 枚举足够;scanner 的回滚 handler 按 subtype 分派,策略集中。

### D2 — Agent 注册表与 preflight 语义

**决策**:模块级 dict `AGENT_REGISTRY: dict[str, AgentSpec]` + `@register_agent(name, agent_type, preflight)` 装饰器;`AgentSpec = namedtuple(name, agent_type, preflight, run)`。

```python
# app/services/detect/registry.py
AGENT_REGISTRY: dict[str, AgentSpec] = {}

def register_agent(name: str, agent_type: Literal["pair", "global"], preflight: PreflightFn):
    def decorator(run_fn: RunFn):
        AGENT_REGISTRY[name] = AgentSpec(name, agent_type, preflight, run_fn)
        return run_fn
    return decorator
```

10 Agent 注册表(pair 型 7 + global 型 3,对齐 US-5.1 AC-5 的 `C(n,2)×7 + 3`):

| name | agent_type | preflight 规则 |
|---|---|---|
| `text_similarity` | pair | 同角色文档存在(对双方)|
| `section_similarity` | pair | 同上 |
| `structure_similarity` | pair | 同上 |
| `metadata_author` | pair | 双方都有 metadata |
| `metadata_time` | pair | 双方都有 metadata(modified_at 非空) |
| `metadata_machine` | pair | 双方都有 metadata(app_version 或 template 非空) |
| `price_consistency` | pair | 双方都有 priced 状态 + price_items |
| `error_consistency` | **global(降级保留)** | identity_info 非空 → 正常;identity_info 空 → **降级运行**(用 bidder.name 纯关键词交叉),不 skipped |
| `style` | global | 至少 2 个 bidder 有同角色文档 |
| `image_reuse` | global | 至少 2 个 bidder 提取到图片 |

`preflight` 函数签名:`async def preflight(ctx: AgentContext) -> PreflightResult`;返 `PreflightResult(status: Literal["ok", "skip", "downgrade"], reason: str | None)`。`error_consistency` 唯一返 `downgrade` 的 Agent,其他只返 `ok | skip`。

**替代方案**:
- 类继承 `BaseAgent` → Python 多态糖多但引实例化成本、Mock 难,拒绝;纯函数注册更简
- YAML 配置驱动 → 解耦过头,类型安全差,拒绝

### D3 — Agent 并行调度 + 超时 + 异常隔离

**决策**:asyncio.gather + return_exceptions + asyncio.wait_for 双层超时。

```python
# app/services/detect/engine.py (伪代码)
async def run_detection(project_id: int, version: int):
    project = await load_project(project_id)
    bidders = await load_bidders(project_id)
    agent_tasks = await create_agent_task_rows(project_id, version, bidders)

    coros = [_run_single_agent_task(task) for task in agent_tasks]
    try:
        await asyncio.wait_for(
            asyncio.gather(*coros, return_exceptions=True),
            timeout=GLOBAL_TIMEOUT_S,  # 30 * 60
        )
    except asyncio.TimeoutError:
        # 全局超时:标所有未完成为 timeout
        await mark_all_running_as_timeout(project_id, version)

    await judge_and_create_report(project_id, version)
    await broker.publish(project_id, "report_ready", {...})
    await update_project_status(project_id, "ready")
```

单 Agent:

```python
async def _run_single_agent_task(task: AgentTask):
    async with track(subtype="agent_run", entity_type="agent_task", entity_id=task.id):
        try:
            pf = await spec.preflight(ctx)
            if pf.status == "skip":
                await mark_skipped(task, pf.reason)
                return
            ctx.downgrade = (pf.status == "downgrade")
            result = await asyncio.wait_for(spec.run(ctx), timeout=AGENT_TIMEOUT_S)
            await mark_succeeded(task, result)
        except asyncio.TimeoutError:
            await mark_timeout(task)
        except Exception as e:
            await mark_failed(task, str(e)[:500])
        finally:
            await broker.publish(project_id, "agent_status", {...})
```

**替代方案**:
- `anyio.TaskGroup` → asyncio.gather 已够,anyio 引入额外依赖,拒绝
- 进程池跑每个 Agent → C6 dummy Agent 无 CPU 负载,进程池开销超过收益;C7 真 CPU Agent 时,`spec.run(ctx)` 内部按需调 `loop.run_in_executor(cpu_executor, ...)`,不改框架

**Risks**:
- `asyncio.wait_for` Python 3.11+ 在超时时 cancel 内部协程,但 cancel 期间协程可能继续占用资源(尤其是 run_in_executor 已 submit 到进程池的任务无法真 cancel)→ C6 dummy Agent 用纯 asyncio.sleep,无此问题;C7 真 CPU Agent 实施时配 Process.kill() 强制终止(requirements RISK-18 已提,C6 不实施,留 TODO)

### D4 — 综合研判占位评分公式

**决策**:按 requirements §F-RP-01 的 10 维度加权求和。

```python
# app/services/detect/judge.py
DIMENSION_WEIGHTS: dict[str, float] = {
    "text_similarity": 0.12,
    "section_similarity": 0.10,
    "structure_similarity": 0.08,
    "metadata_author": 0.10,
    "metadata_time": 0.08,
    "metadata_machine": 0.10,
    "price_consistency": 0.15,
    "error_consistency": 0.12,  # 铁证维度,权重最高之一
    "style": 0.08,
    "image_reuse": 0.07,
}
# 合计 1.00

def compute_report(pair_comparisons, overall_analyses) -> (total_score, risk_level):
    per_dim_max = {}  # dim -> max score across all pairs
    for pc in pair_comparisons:
        per_dim_max[pc.dimension] = max(per_dim_max.get(pc.dimension, 0), pc.score)
    for oa in overall_analyses:
        per_dim_max[oa.dimension] = max(per_dim_max.get(oa.dimension, 0), oa.score)
    total = sum(per_dim_max.get(d, 0) * w for d, w in DIMENSION_WEIGHTS.items())
    if any(pc.is_ironclad for pc in pair_comparisons):
        total = max(total, 85)  # 铁证命中 → 强制至少高风险
    if total >= 70: level = "high"
    elif total >= 40: level = "medium"
    else: level = "low"
    return round(total, 2), level
```

**理由**:
- "每维度取跨投标人最高分"是简化版 US-5.1 AC 的 "`报告对每个维度取最高分`"
- 铁证 = `is_ironclad=true` 的 PairComparison 强制至少 high,对齐 requirements §F-RP-01 + US-6.1 AC-2
- 权重是占位,C14 可调;C6 只保证"通路通"

**替代方案**:
- LLM 结论生成 → C14 做
- 跨维度相关性建模 → 远超 C6 范围,拒绝

### D5 — SSE 事件 schema(复用 C5 broker,扩事件类型)

**决策**:沿用 C5 `progress_broker.publish(project_id, event_type, data)` 接口,C6 新增 2 个 event_type(原 C5 是 parse-related 5 种 + heartbeat):

```json
// agent_status
{"event": "agent_status", "data": {
  "version": 3,
  "agent_task_id": 125,
  "agent_name": "text_similarity",
  "agent_type": "pair",
  "pair": {"a": 10, "b": 11},  // null for global
  "status": "succeeded",  // pending|running|succeeded|failed|timeout|skipped
  "score": 42.5, "summary": "...", "elapsed_ms": 1234
}}

// report_ready
{"event": "report_ready", "data": {
  "version": 3,
  "total_score": 67.5,
  "risk_level": "medium",
  "completed_count": 10,
  "skipped_count": 0,
  "failed_count": 0,
  "timeout_count": 0
}}
```

SSE 端点 `GET /api/projects/{pid}/analysis/events`:首帧推 snapshot(当前 version 所有 AgentTask 状态),后续推事件。断线重连 → 客户端调 `/analysis/status` 重建快照。

**替代方案**:
- WebSocket → 只需要 server-push,SSE 轻量;拒绝
- 轮询 → 前端降级模式已做,首选 SSE;拒绝

### D6 — async_tasks 心跳机制与 scanner 扫描频率

**决策**:
- 心跳间隔:30s(worker 协程每 30s UPDATE heartbeat_at)
- Stuck 阈值:60s(> 2 倍心跳间隔,避免 GC 抖动误判)
- Scanner 扫描时机:**后端启动时一次**(阻塞等待 scan 完成)+ 无周期扫描

**理由**:
- 启动时扫一次解决"进程重启丢任务"核心场景;周期扫描是过度设计(正常运行没有 stuck,有 stuck 只会是重启 + 崩溃两个场景)
- 30s / 60s 阈值对用户无感(启动后最多 1min 看到 stuck 任务状态);若以后需更快反应可改 10s / 20s
- 启动阻塞扫描:避免"启动后有个窗口期用户看到项目 analyzing 但其实 Agent 都 stuck"的幻觉

**替代方案**:
- 后台 30s 周期扫 → 过度设计,生产期望无 stuck
- celery beat / cron → 引重,拒绝

**Risks**:
- 若 scan 很慢(100+ stuck 行)会卡后端启动;mitigation:scan 限制单次最多处理 1000 行,超出延后下次启动再扫

### D7 — Agent 执行上下文 AgentContext 数据载荷

**决策**:`AgentContext` 包一次性加载的项目级数据,传给 preflight 和 run。

```python
@dataclass
class AgentContext:
    project_id: int
    version: int
    agent_task: AgentTask  # 本次任务的 DB 对象
    bidder_a: Bidder | None  # pair 型两侧;global 型全 None
    bidder_b: Bidder | None
    all_bidders: list[Bidder]  # global 型用
    llm_provider: LLMProvider | None  # C6 dummy 不用;C7~C13 用
    session: AsyncSession
    downgrade: bool = False  # error_consistency 降级标志
```

**理由**:
- 单一入口,Agent 实现不直接 query DB(可 Mock)
- `llm_provider` 字段留接口,C6 dummy Agent 不 touch;C14 综合研判接 LLM 也走这里

### D8 — "启动检测"前置校验与 version 分配

**决策**:前置校验顺序(失败立即返 400 / 409):

1. 项目未软删 + 权限校验(owner 或 admin)
2. project.status ∈ `{'ready', 'completed'}`(`'analyzing'` → 409;`'draft' / 'parsing'` → 400)
3. bidder 数 ≥ 2(否则 400 "至少需要2个投标人")
4. 所有 bidder.parse_status ∈ 终态集 `{identified, priced, price_partial, identify_failed, price_failed, skipped, needs_password}`(否则 400 "请等待所有文件解析完成")
5. `version = max(agent_tasks.version WHERE project_id=? , 0) + 1`(失败 version 占位,不复用)
6. 批量 INSERT AgentTask 行(事务)+ UPDATE project.status = 'analyzing'
7. `asyncio.create_task(run_detection(project_id, version))` 异步启动

**幂等**:步骤 2 若 `analyzing` → 返 409 + `{current_version, started_at}`;客户端前端跳转进度面板。

### D9 — ProcessPoolExecutor 接口预留

**决策**:模块级单例 `CPU_EXECUTOR: ProcessPoolExecutor | None = None` + `get_cpu_executor() -> ProcessPoolExecutor`:lazy 初始化,maxworkers = `os.cpu_count() or 2`;Agent 内部按需 `await loop.run_in_executor(get_cpu_executor(), fn, *args)`。

C6 dummy Agent 不调 `get_cpu_executor`;C7 首个 CPU 密集 Agent 实施时消费。

**理由**:user prompt 原话 "异步任务框架(asyncio + ProcessPoolExecutor)",留接口但不强跑,避免 dummy Agent 白烧进程池开销。

### D10 — 前端报告页路由与骨架范围

**决策**:
- 路由:`/reports/:projectId/:version`(与 C14 共用,C6 只实现 Tab1)
- Tab1 骨架:
  - 顶栏:风险等级徽章(红/橙/绿,带总分)+ version 选择器(若 > 1)
  - 主体:10 维度得分列表,按 `is_ironclad` 降序 + `score` 降序
  - 每行:维度名 / 得分 / 状态(succeeded/skipped/failed/timeout)/ summary(单行文本)
  - LLM 结论区:占位卡片 "AI 综合研判暂不可用 — 将在后续版本支持"
- 不做:雷达图 / 热力图 / Markdown / 4 Tab 切换 / 证据详情抽屉

**替代方案**:
- 做占位 4 Tab 切换但内容留空 → 用户误以为功能缺失,拒绝;直接只做 Tab1,清楚信号"待后续填充"

## Risks / Trade-offs

- **[Risk-1] asyncio.wait_for 超时后 cancel 无法真中断 executor 任务** → C6 dummy 用 asyncio.sleep 不触发;C7 真 CPU Agent 留 TODO(requirements RISK-18 已记)
- **[Risk-2] scanner 扫描启动阻塞** → 限制单次最多处理 1000 行 + 失败 handler 个独立 try,不互相影响;超出延后下次扫
- **[Risk-3] 10 Agent 注册表全局单例,测试不隔离** → `INFRA_DISABLE_DETECT=1` 跳过自动调度;单元测试直接调 `AGENT_REGISTRY["name"].run(mocked_ctx)`,不走 engine
- **[Risk-4] async_tasks 表无 unique 约束,重复心跳 worker 可能插 2 行** → tracker 用上下文管理器保证 1 task 1 行;异常路径 finally 块负责清理
- **[Risk-5] global Agent(error_consistency / style / image_reuse)无 pair_bidder_a/b,AgentTask 表字段 nullable** → schema 定义 pair_bidder_a_id / pair_bidder_b_id 均 nullable + CHECK `(agent_type='pair' AND pair_bidder_a_id IS NOT NULL AND pair_bidder_b_id IS NOT NULL) OR (agent_type='global' AND pair_bidder_a_id IS NULL AND pair_bidder_b_id IS NULL)`(仅 PostgreSQL 走 CHECK,SQLite 应用层保证)
- **[Risk-6] 启动扫描可能把正常运行中的 task 标为 timeout**(若刚启动的 worker 第一次心跳还没写入就被扫到) → tracker 上下文管理器内 INSERT 行时 `heartbeat_at = now()`,不依赖首次 UPDATE;扫描阈值 60s 给足缓冲

## Migration Plan

### 上线步骤

1. `alembic upgrade head` 创建 5 张新表(agent_tasks / pair_comparisons / overall_analyses / analysis_reports / async_tasks)+ 1 索引 `(status, heartbeat_at)` on async_tasks
2. 后端部署新版本:启动时 scanner 扫 async_tasks 空表 → no-op
3. 前端部署新版本:ReportPage 路由 + StartDetectButton 激活
4. 用户首次点击"启动检测" → 验证 10 AgentTask 行正确建立 + SSE 推进度 + 报告行落地 + 风险等级徽章显示

### 回滚策略

- DB 回滚:`alembic downgrade 0004_parser_pipeline` 按 FK 反序 DROP 5 张表(agent_tasks 依赖 projects/bidders;pair_comparisons/overall_analyses/analysis_reports 依赖 projects;async_tasks 无 FK)
- 代码回滚:撤回 C6 commit 即可;不影响 C5 及以前功能

## Open Questions

- **Q1**(延后至 C14):`llm_conclusion` 文本字段应该是 `TEXT` 还是 `JSONB`(结构化多段)?C6 占空字符串,C14 明确
- **Q2**(延后至 C7):`error_consistency` 降级模式下 `preflight` 返 `downgrade` 状态时,`AgentTask.summary` 是否要标记 "降级检测"?C6 先不标,C7 `error_consistency` 实施时定
- **Q3**(实施期决):`ProcessPoolExecutor` maxworkers 默认值 — C6 预留 `os.cpu_count() or 2`,但容器环境下 `cpu_count` 可能返 host 全部核,生产可能需读 `cgroup` → 留 C7 第一个真消费者验证
