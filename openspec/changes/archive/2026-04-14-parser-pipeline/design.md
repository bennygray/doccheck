## Context

C4 已落地投标人 CRUD / 压缩包上传 / 安全解压 / 报价元配置,前端 ProjectDetailPage 能看到 bidder 卡片与文件树,但`bid_documents.file_role` / `bidders.identity_info` / `price_parsing_rules.column_mapping` 三处字段始终 NULL。C1 已建 LLM 适配层(`app/services/llm/`,OpenAI-compat Provider + Mock fixture)与 SSE 骨架(`/demo/sse` 定时 heartbeat),但从未真实调用过 LLM,也从未推过业务事件。

C5 是 M2 第三个(也是最后一个)change。完成后 M2 的"上传压缩包 → 自动解析 → 看到投标人+文件角色+报价"端到端闭环。

C5 propose 阶段与用户敲定 5 项关键边界(proposal.md 已列):

- **A1 整体做**:不拆 C5a/C5b
- **B1 完整 SSE 事件流**:5 类事件推送给前端
- **C2 + β**:LLM 识别规则即自动 `confirmed=true` 批量回填;全 sheet 成功才 `priced`,部分 → `price_partial`
- **D2 人工修正**:改角色/改列映射做完,管理员关键词维护留 C17
- **E3 DB 原子占位**:报价规则"仅一次识别"由 DB 唯一约束 + asyncio.Event + poll 三层实现

另一项**约束性事实**:**报价表是可选维度**——不是所有 bidder 都有报价表(纯资质/纯技术投标项目),`identified` 本身即终态;`priced` 仅对"有报价表的 bidder"才是进一步状态。这条不是决策,是项目性质,贯穿状态机设计。

## Goals / Non-Goals

**Goals:**

- 完成 US-4.2(内容提取)/ US-4.3(角色分类+身份信息)/ US-4.4(报价规则确认与批量回填)三个 User Story 的完整实现
- LLM 两个调用点(角色分类 + 报价规则识别)首次真实落地,LLM 失败时有可观察的兜底路径
- bidder.parse_status 从 C4 的"解压域"扩展到"LLM 识别 + 报价域",覆盖完整生命周期
- 前端实时看到解析进度(SSE 事件流),SSE 断开自动降级轮询
- 审查员可在 UI 直接修正 LLM 错判(改文档角色 / 改列映射并重新回填)
- 报价规则"项目级仅一次识别"并发控制可靠,多 bidder 同时解析不会重复调 LLM
- **消化 C4 "event loop 重启丢任务" follow-up 的报价规则这一半**(E3 借 DB 做状态持久化)

**Non-Goals:**

- **不实现检测流水线**(C6~C17 范围);C5 只到"identified/priced"为止,`project.status=parsed` 态不触发任何检测
- **不实现管理员后台**(改关键词列表需发版改 Python 常量;admin UI 留 C17)
- **不实现 LLM 置信度分支**(C3 决策里的 low confidence 标"待确认"本期降级为"规则兜底命中即为 high,否则 low";不引入 LLM 自评置信度)
- **不实现 DOC/XLS/PDF 解析**(沿用 C4 `parse_status='skipped'`,错误文案 "暂不支持 X 格式")
- **不实现断点续传/增量更新**:re-parse 端点覆盖式重跑该文档的整个 pipeline;不做"只重跑失败阶段"
- **不实现 ProcessPoolExecutor**:继续用 asyncio.create_task(C4 B1 决策延伸);CPU 密集的 pHash 计算量小可接受
- **不实现跨进程 SSE**:多 worker 部署下,一个项目的 SSE 订阅者如果连到不同 worker 看不到同一事件流。当前单机单 worker 部署,不修;正式多实例部署时走 Redis pub/sub 升级留 C17+
- **不实现报价数据审核流程**:回填完立即可见,用户不用"审核"这批数据
- **不消化"加密包 3 次冻结"follow-up**(仍留 C17)与"解压阶段 event loop 重启丢任务"(仍留 C6 任务表)

## Decisions

### D1. LLM 角色分类与身份信息提取 = 一次调用合并

**Decision**:一个 bidder 的所有 DOCX/XLSX 文件,其文件名 + 每个文件首段文本(前 500 字符)一起拼成一次 LLM 调用;prompt 要求 LLM 同时返回 `{roles: [{document_id, role, confidence}], identity_info: {...}}`。

**Rationale**:

- US-4.3 原文明确"**一次调用同时完成两项任务**"(任务1 角色分类 + 任务2 身份信息提取)
- 身份信息(公司全称/简称/项目经理/资质编号)分散在多个文件,LLM 需同时看到所有文件才能抽;拆两次调用等于重复喂上下文
- Token 成本:per bidder ~3~10 个文件 × 500 字 首段 + 文件名列表 ≈ 5k~8k tokens,一次调用足够

**Alternatives considered**:

- 角色 + 身份分两次调用 → 拒绝,重复喂 context + 两次 LLM 超时点
- 每文件一次调用 → 拒绝,上下文碎片化,身份信息跨文件关联会漏

### D2. LLM 调用失败兜底:角色走规则,身份走空

**Decision**:`role_classifier.py` 收到 LLMResult.error 非 None(timeout/rate_limit/bad_response)时:

- **角色分类**:fallback 到 `role_keywords.py` 关键词匹配,9 种角色依次尝试,首次命中即定角色;全未命中 → `role='other'` + `role_confidence='low'`(前端黄色徽章"待确认")
- **身份信息**:不做规则兜底(关键词抽实体很容易抽错人名/编号)→ `bidders.identity_info = NULL`;bidder.parse_status 进入 `identified`(身份缺失不阻塞后续流程);前端在 bidder 详情页显示"身份信息未提取,可手动补充"提示(本期只显示提示,**不做手动补充 UI**,留 C17)

**Rationale**:

- 角色分类是后续"同角色文档对比"的基石,必须给值,哪怕是 `other`;规则兜底的精度足够覆盖 80% 场景(文件名通常含"报价/技术方案/投标函"等关键词)
- 身份信息 NULL 不阻塞"错误一致性"检测(C10 会跳过无身份 bidder),但强行规则抽会污染后续检测结果,宁缺毋滥

**Alternatives considered**:

- LLM 错 → bidder 整体标 `identify_failed` → 拒绝,太激进,用户只能手动补救所有东西
- 规则兜底同时抽身份信息 → 拒绝,精度太低

### D3. 报价规则识别并发控制 = DB 原子占位 + asyncio.Event + DB poll 三层

**Decision**:

- 先决条件:`price_parsing_rules` 加 `status` 字段(`identifying | confirmed | failed`)+ 唯一约束 `UNIQUE(project_id) WHERE status IN ('identifying','confirmed')`(通过 postgres partial unique index 实现)
- 每 bidder 协程到达"报价识别"阶段时:
  1. 尝试 `INSERT INTO price_parsing_rules (project_id, status='identifying', ...)`;唯一约束冲突 → 进入"等规则"路径
  2. **胜出者**:调 LLM 识别 → UPDATE `status='confirmed', column_mapping=..., confirmed=true`(C2 决策走自动 confirmed);失败 → UPDATE `status='failed'`;两种终态都通过 project 级 `asyncio.Event.set()` 通知等待者
  3. **等待者**:先 `await event.wait_for(timeout=10s)` 快路径;timeout 或进程重启后 event 丢失 → 进入 DB poll 慢路径(每 3s 查 `price_parsing_rules.status`,最多 5 分钟);仍 identifying → 失败该 bidder 的报价回填(bidder 状态 `price_failed`,报价未识别)
- 模块级 `_RULE_EVENTS: dict[int, asyncio.Event]`(project_id → Event),进程内缓存;清理由 LRU + 规则完成后显式 pop 双兜底

**Rationale**:

- **可靠性**:DB 唯一约束是硬保证,多 worker 部署也成立(asyncio.Lock 只在单进程有效)
- **重启鲁棒**:event 丢失后走 DB poll 作为第二层;poll 5 分钟仍未有结果 → 说明 identifying 协程真丢了,该 bidder 标 `price_failed`,用户可重试 re-parse
- **吃掉 C4 follow-up 的一半**:报价规则这个状态点完全由 DB 管,重启后行为确定

**Alternatives considered**:

- asyncio.Lock per project → 拒绝,进程内状态,重启/多 worker 都挂
- Coordinator 单点协程 → 拒绝,多一层抽象,Coordinator 自己也会挂
- 裸 DB poll(无 event 快路径)→ 拒绝,正常路径白等 3s 没必要

### D4. 报价回填时机 = 用户无需确认,LLM 规则一出立即批量回填

**Decision**:`price_rule_detector` 返回有效规则(schema 校验通过)→ 立即设 `confirmed=true` → 触发 **所有已 `identified` 且未 `priced` 的 bidder 的报价回填协程**(含规则生成时尚未到达报价阶段的 bidder:他们到阶段时 INSERT 失败,进等待路径,拿到 confirmed=true 规则后直接回填,跳过 LLM 识别);用户事后点"修正列映射"按钮会触发 `PUT /price-rules/{id}` → 更新 column_mapping → 清空该项目所有 bidder 的 PriceItem → 重新回填

**Rationale**:

- C2 决策:LLM 识别即视为可信;用户修正是兜底而非日常路径
- 项目级统一规则语义要求:修正后所有 bidder 统一重回填,不能部分 bidder 用旧规则、部分用新规则
- 重回填 = 先 DELETE 全部 price_items + 重跑回填协程;L2 测试验证 DELETE 成功再 INSERT

**Alternatives considered**:

- 用户点"确认"才批量应用(C1 路径)→ 已被 propose 阶段 C 轴排除
- 增量回填(只补新 bidder)→ 规则改了同项目所有 bidder 都该按新规则,增量会引入不一致

### D5. bidder.parse_status 状态机扩展

**Decision**:在 C4 6 态基础上新增 7 态,总计 13 态:

| 阶段 | 态 | 来源 |
|---|---|---|
| 压缩包阶段 | `pending / extracting / needs_password` | C4 |
| 解压终态 | `extracted / partial / failed` | C4 |
| LLM 识别中 | `identifying` | **C5 新**(内容提取+LLM 一次调用,合并成一段) |
| LLM 识别终态 | `identified / identify_failed` | **C5 新** |
| 报价回填中 | `pricing` | **C5 新**(仅有报价表的 bidder 才经此态) |
| 报价回填终态 | `priced / price_partial / price_failed` | **C5 新** |

状态流转图(简化):

```
pending → extracting → extracted ─┬─► identifying ─┬─► identified ─┬─► pricing ─┬─► priced
                                  │                │               │            ├─► price_partial
                                  │                │               │            └─► price_failed
                                  │                │               └─► (无报价表) = 终态
                                  │                └─► identify_failed (终态)
                                  ├─► partial(解压部分成功)─► 可继续 identifying
                                  ├─► failed(终态)
                                  └─► needs_password ─► 密码对后回 pending
```

**文档级 bid_documents.parse_status**:C4 已有 5 态,C5 新增 `identifying / identified / identify_failed`;文档级**不**进 priced(报价只对 bidder 有意义,不对单文档)

**Rationale**:

- 内容提取与 LLM 识别合并到 identifying 单一态 —— 两者是"为同一个 LLM 调用做准备"的连续动作,切分会让状态面膨胀到 16 态,得不偿失;失败只产生一个 `identify_failed`(parse_error 字段记具体阶段)
- 报价相关态单独分 3 个(pricing/priced/price_partial)是因为 β 方案下需要显式区分"全成功"vs"部分成功"vs"全失败"

**Alternatives considered**:

- 不加 `pricing` 中间态,直接 `identified → priced` → 拒绝,多 sheet 回填需要可观察进行中态,否则 UI 闪烁
- `identify_failed`/`price_failed` 合并为 `parse_failed` → 拒绝,丢失阶段信息,用户重试时不知道重哪段

### D6. SSE 事件流设计

**Decision**:`GET /api/projects/{pid}/parse-progress` 返 SSE 流(StreamingResponse + text/event-stream),事件类型:

| event | data payload | 触发时机 |
|---|---|---|
| `bidder_status_changed` | `{bidder_id, old_status, new_status}` | 每次 bidder.parse_status 变更 |
| `document_role_classified` | `{document_id, role, confidence}` | 文档角色由 LLM/规则定下来 |
| `project_price_rule_ready` | `{rule_id, confirmed, sheet_name}` | 报价规则首次 confirmed |
| `bidder_price_filled` | `{bidder_id, items_count, partial_failed_sheets}` | bidder 报价回填完成 |
| `error` | `{bidder_id?, stage, message}` | 任何 identify/price 失败 |
| `heartbeat` | `{ts}` | 每 15s(对齐 C1 demo) |

**实现**:

- `progress_broker.py` 内存 broker,`dict[project_id, list[asyncio.Queue]]` 维护订阅者列表
- pipeline 协程调用 `broker.publish(project_id, event)` → 异步写入所有 queue
- SSE 端点订阅时从 broker 拿 queue + 发送 DB 当前态 snapshot 作为首帧(便于断线重连重新对齐)
- 客户端断开 → `asyncio.CancelledError` → 从 broker 移除 queue

**前端降级**:

- `useParseProgress(projectId)` hook:EventSource onerror → `setInterval(() => refetchProject(), 3000)`;onmessage 恢复时清掉 interval
- SSE 失败不影响功能,只影响实时性

**Rationale**:

- SSE 而非 WebSocket:单向推送,HTTP 兼容,不需要升级协议,nginx 反代友好(加 `X-Accel-Buffering: no` 即可)
- 内存 broker 单进程足够(当前部署场景);多进程升级留 C17+
- 首帧 snapshot 简化断线重连逻辑(不用维护 lastEventId 序号)

**Alternatives considered**:

- WebSocket 双向 → 拒绝,解析阶段没有客户端→服务端消息
- 仅推送状态变更事件,不推细节(B2 方案)→ 已被 propose 阶段 B 轴排除
- 使用 SSE 库(sse-starlette)→ 拒绝,FastAPI 原生 StreamingResponse 已够用,新增依赖得不偿失

### D7. 数据模型 4 张新表字段决策

- **`document_texts`**:按段落存而非整文档 concat;`paragraph_index` 保留源序;`location` 区分正文/页眉脚/文本框/表格行,满足 US-4.2 AC-3(页眉页脚不参与相似度)
- **`document_metadata`** 1:1 关联 bid_document:作者/最后修改人/公司/软件指纹 统一抽;值缺失写 NULL 不抛错
- **`document_images`**:md5 CHAR(32)+ phash CHAR(64) 作为后续图片相似度检测的基石;file_path 存图片落盘路径(`extracted/<pid>/<bid>/<hash>/imgs/`)
- **`price_items`**:`quantity Numeric(18,4)`(数量可能带小数如"工日"的 1.5)`/ unit_price Numeric(18,2) / total_price Numeric(18,2)`(对齐 C3 金额精度);`(bidder_id, price_parsing_rule_id, sheet_name, row_index)` 复合索引满足"改规则后 DELETE 重跑"查询
- **索引**:`document_texts(bid_document_id, paragraph_index)` / `document_metadata(bid_document_id)` / `document_images(bid_document_id, md5)` / `price_items(bidder_id, price_parsing_rule_id)`

### D8. 角色关键词常量位置

**Decision**:`app/services/parser/llm/role_keywords.py`,结构:

```python
ROLE_KEYWORDS: dict[str, list[str]] = {
    "technical": ["技术方案", "技术标", "技术建议书"],
    "construction": ["施工组织", "施工方案", "施工设计"],
    "pricing": ["报价", "清单", "工程量", "商务标", "投标报价"],
    "unit_price": ["综合单价", "单价分析"],
    "bid_letter": ["投标函", "投标书"],
    "qualification": ["资质", "资格", "营业执照"],
    "company_intro": ["企业介绍", "公司简介", "公司概况"],
    "authorization": ["授权", "委托"],
}  # 未命中 → "other"
```

**Rationale**:US-4.3 AC-7 字面"管理员在规则配置中维护"本期降级(D2 决策);文件放 services 层是因为逻辑上属于解析兜底规则,非独立 config 模块;C17 搭 admin 后台时迁到 DB + admin UI 即可,导入点仅 `role_classifier.py` 一处。

### D9. HTTP 413/422 常量名顺手修

**Decision**:替换 `bidders.py` / `documents.py` / `price.py` / `projects.py` 等路由中的 `status.HTTP_413_REQUEST_ENTITY_TOO_LARGE` / `status.HTTP_422_UNPROCESSABLE_ENTITY` 为 `status.HTTP_413_CONTENT_TOO_LARGE` / `status.HTTP_422_UNPROCESSABLE_CONTENT`(FastAPI 新常量名);无行为变化,仅消除 deprecation warning;一条 [impl] 任务覆盖。

## Risks / Trade-offs

- **[Risk] LLM 返回格式不稳定**(JSON 解析失败)→ Mitigation:`role_classifier.py` / `price_rule_detector.py` 用 `json.loads()` 包 try-except,解析失败视同 `bad_response` 错,走 D2 规则兜底
- **[Risk] 内容提取慢(大 DOCX/XLSX 数百 MB)阻塞事件循环**→ Mitigation:`extract_content` 用 `run_in_executor(None, _sync_parse, ...)` 跑在默认 ThreadPoolExecutor,避免主 loop 卡住;单文件 10 分钟超时,超时标 `identify_failed`
- **[Risk] 报价规则识别胜出者挂掉(OOM / 异常)导致等待者永久等**→ Mitigation:`rule_coordinator` 主逻辑 try-finally,finally 里 `event.set()` + `UPDATE status='failed'`;poll 路径 5 分钟超时作为第三层兜底
- **[Risk] SSE 长连接下游 nginx 超时截断**→ Mitigation:heartbeat 15s 一次 + 响应头 `X-Accel-Buffering: no`;部署文档明示 nginx `proxy_read_timeout` 需 ≥ 60s
- **[Risk] 多 bidder 同时改列映射触发并发重回填**→ Mitigation:`PUT /price-rules/{id}` 串行(项目级 asyncio.Lock,单进程足够);拒绝同步到来的第二个 PUT 返 409
- **[Trade-off] 内存 SSE broker 不支持多进程部署** → 接受;当前单进程部署;多进程升级走 Redis pub/sub 在 C17+ 处理
- **[Trade-off] 角色关键词 Python 常量改动需发版** → 接受;当前只有 1 admin,频次低;C17 升级为 DB+admin UI
- **[Trade-off] 重回填先 DELETE 再 INSERT 有短暂空窗(前端可能刷出空列表)** → 接受;PUT 端点返 200 时前端可显示"规则已更新,回填中...",避免立刻查;或用户 F5 时概率碰到空窗 1~2s

## Migration Plan

1. `alembic upgrade head` 执行 0004 迁移:建 4 张新表 + 扩 parse_status 枚举白名单(应用层校验,不是 DB enum)+ 加 price_parsing_rules `status` 字段和唯一约束
2. C4 已有 bidder 数据:`parse_status` 枚举值均在 C4 6 态内,不受 C5 扩展影响;继续正常工作
3. C4 已有 price_parsing_rules 骨架数据:C4 阶段表为空(C4 PUT 端点骨架未真实写入),无兼容性问题
4. **回滚策略**:`alembic downgrade 0003_files` 还原;需配套回滚代码到 C4(4 张新表无数据丢失风险,price_parsing_rules 新增的 status 字段 drop 即可)
5. 部署前端新版本时,老版本不会订阅 SSE 端点(API 新增),不会中断;老版本轮询 `GET /api/projects/{pid}` 依然拿得到 progress(C5 扩展字段不会删)

## Open Questions

- LLM Prompt 第一版效果:角色分类 9 种的 prompt 需要真实跑过 3~5 个样例包才能锁定;第一版 prompt 写进 `prompts.py` 后,manual 测试环节会调整,留做 C5 实施期的小改动,不阻塞 propose
- `document_images.phash` 算法选型:用 `imagehash.phash`(标准 DCT pHash)还是 `dHash`?→ 留给实施期快速决;默认走 pHash,phash 长度 64bit 已在字段类型固定
- 报价表 header 多行(如 2 行合并表头)的 sheet:LLM 识别 `header_row` 当前按单行 int 存;遇到多行真实样例再扩展为 `header_rows: int[]`(不进本期 schema)
