## MODIFIED Requirements

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

### Requirement: 10 Agent 骨架文件与 dummy run

后端 MUST 在 `app/services/detect/agents/` 下提供 **11** 个 Agent 骨架文件(原 10 + C12 新增 `price_anomaly.py`),每个文件定义一个 Agent 骨架,通过 `@register_agent` 装饰器注册到 AGENT_REGISTRY。

C12 归档后,Agent `text_similarity`(C7)、`section_similarity`(C8)、`structure_similarity`(C9)、`metadata_author` / `metadata_time` / `metadata_machine`(C10)、`price_consistency`(C11)、`price_anomaly`(**C12 新增,直接带真实 run 注册**)的 `run()` 均为真实算法,不走 dummy;其余 3 个 global Agent(`error_consistency / style / image_reuse`)`run()` 继续走 dummy,直至 C13 替换。

每个尚未替换为真实实现的骨架文件 MUST 含:
- `preflight` 函数(按 "Agent preflight 前置条件自检" Requirement 规则)
- `run(ctx: AgentContext) -> AgentRunResult` 函数,dummy 实现:
  - `await asyncio.sleep(random.uniform(0.2, 1.0))`
  - `score = random.uniform(0, 100)`
  - `summary = f"dummy {name} result"`
  - pair 型:INSERT PairComparison 行(随机 is_ironclad 但权重 < 10%)
  - global 型:INSERT OverallAnalysis 行
  - 返 `AgentRunResult(score=score, summary=summary)`

`AgentRunResult` 是 namedtuple,字段:`score: float, summary: str, evidence_json: dict = {}`。当整 Agent 因数据缺失 run 级 skip 时 `score=0.0` 作为哨兵值,evidence 层通过 `participating_fields=[]`(或 `participating_dimensions=[]` / `participating_subdims=[]`,按 Agent 定义)标记。

C13 各 change 替换对应 `run()` 实现,不改 preflight、不改文件名、不改注册 key。

**注意**:C12 归档后,7 个 pair 型 Agent + 1 个 global 型 Agent(`price_anomaly`)的 `run()` 全部已替换为真实算法;dummy 列表仅剩 3 个 global 型 Agent(`error_consistency / style / image_reuse`)。

#### Scenario: 11 Agent 模块加载后注册表完整

- **WHEN** `from app.services.detect import agents` 触发所有 agents 模块加载
- **THEN** `AGENT_REGISTRY` 含 11 条目;每条 `run` 可调

#### Scenario: dummy run 产生 OverallAnalysis 行

- **WHEN** 调 style dummy run(global 型,C12 后仍为 dummy)
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

- **WHEN** 调 `AGENT_REGISTRY["metadata_time"].run(ctx)` 且元数据足够
- **THEN** `evidence_json["algorithm"] == "metadata_time_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: metadata_machine 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["metadata_machine"].run(ctx)` 且元数据足够
- **THEN** `evidence_json["algorithm"] == "metadata_machine_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: price_consistency 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["price_consistency"].run(ctx)` 且双方 PriceItem 存在
- **THEN** `evidence_json["algorithm"] == "price_consistency_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: price_anomaly 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["price_anomaly"].run(ctx)` 且项目下 ≥ 3 家 bidder 已成功解析报价
- **THEN** `evidence_json["algorithm"] == "price_anomaly_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

---

## ADDED Requirements

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
