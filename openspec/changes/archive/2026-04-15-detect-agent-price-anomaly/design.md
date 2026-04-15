## Context

C11 已完成 pair 间水平关系检测(`price_consistency`,4 子检测:tail / amount_pattern / item_list / series_relation)。C12 对应 execution-plan §3 "垂直关系"场景:**单家 bidder vs 项目群体**的异常低价检测。

**关键事实核对(propose 期):**
- execution-plan §3 C12 命名为 `price_anomaly`,但 C6 注册表仅 10 Agent(pair 7 + global 3 = `text_similarity / section_similarity / structure_similarity / metadata_author / metadata_time / metadata_machine / price_consistency` + `error_consistency / style / image_reuse`)**不含 `price_anomaly`**
- `price_anomaly` 语义是 "1 家 vs 全体",是天然的 global 型 Agent,不是 pair 型
- 本 change 显式扩注册表 10 → 11(pair 7 + global 4)

**产品级决策已锁(propose 期 Q&A):**
- Q1:sample_size 下限 = **3 家**(贴原文,覆盖小体量围标高发场景)
- Q2:标底本期 **不支持**,预留 hook 留 follow-up(M3 scope 收缩;原 execution-plan §3 C12 原文兜底"标底未配置 → 仅按均值判断"对齐)
- Q3:偏离方向 = **仅负偏离(low)**;档位 = **30% 中档**(env 可覆盖)
- Q4:本期 **纯程序化,LLM 解释全留 C14**(贴 C11 模式,避免 C12/C14 重复)

**C12 消费的数据:**
- `price_items` 表(C5 产出):每 bidder 报价明细行(unit_price / total_price / item_name / sheet_name 等)
- `bid_documents` 表:bidder 的 parse_status(过滤 `parse_status='priced'`)
- **不消费** `project_price_configs.currency / tax_inclusive`(C11 Q2 决策一致:口径归一化留 C14)

**M3 进度:** 6/9 → 7/9(本 change 归档后)

## Goals / Non-Goals

**Goals:**
- 新增 `price_anomaly` global Agent,纯程序化检测"单家负偏离 > 30%"(默认)
- 注册表从 10 Agent 扩至 11 Agent,spec "10 Agent 注册表" Requirement MODIFIED
- 复用 C11 `price_impl/` 模式搭建 `anomaly_impl/` 子包(结构对齐)
- 复用 C11 Agent 级 skip 哨兵语义(`score=0.0 + participating_subdims=[]`)
- evidence 结构预留 `baseline: null` + `llm_explanation: null` 两个 follow-up hook 字段
- L1 + L2 测试覆盖:env 加载 / extractor / detector / scorer / preflight + 4 E2E Scenario

**Non-Goals:**
- 标底(baseline)检测路径 — 预留字段但不实现(follow-up,可能走 C17 admin 后台或独立 baseline change)
- LLM 语义解释(如"低价是否合理") — 全留 C14
- 项目类型区分(总包 vs 单项走不同阈值) — 本期统一阈值,实战反馈后 follow-up
- 正偏离 / 双向偏离检测 — env `DIRECTION` 预留 `high/both` 值但本期仅实现 `low` 分支
- 含税/币种归一化 — 贴 C11 Q2 决策,全留 C14
- 修改 engine / judge / context / registry 装饰器契约(仅改 `EXPECTED_AGENT_COUNT` 常量)

## Decisions

### D1:扩注册表至 11 Agent,新增 `price_anomaly` 为 global 型

**选择:** registry 常量 `EXPECTED_AGENT_COUNT: int = 11`;`@register_agent(name="price_anomaly", agent_type="global", preflight=...)` 装饰器注册。spec "10 Agent 注册表" Requirement MODIFIED 为 "11 Agent 注册表",pair 7 + global 4。

**备选:**
- **B. 合并进 C14 LLM 综合研判**:异常低价 80% 是纯程序化规则(偏离 N%),LLM 没必要;丢失 Agent 级启停/独立 evidence/前端单独展示粒度;C14 膨胀不合理 → 拒绝
- **C. 复用既有 global Agent 名(如 `style`)**:没有语义贴的既有名(error_consistency 错误共现 / style 格式 / image_reuse 图片);强行塞入等于重命名 → 拒绝

**Rationale:** "单家 vs 群体"是明确物理 global 关系,独立 Agent 语义清晰;engine INSERT global 行逻辑已就绪(`pair_bidder_a_id=NULL, pair_bidder_b_id=NULL`),扩注册表是最小改动;第一性原理审:10 不是物理必然,是设计期 estimate,扩至 11 是真信号显式化。

### D2:子包结构 `anomaly_impl/` 对齐 C11 `price_impl/`

**选择:** `backend/app/services/detect/agents/anomaly_impl/` 5 文件:
- `__init__.py`(可选共享 helper)
- `config.py`(7 env + dataclass `AnomalyConfig` + `load_anomaly_config()`)
- `models.py`(TypedDict `AnomalyOutlier` / `BidderPriceSummary`)
- `extractor.py`(从多 bidder 聚合 `total_price` 求和汇总)
- `detector.py`(均值计算 + 偏离判定 + outliers 产出)
- `scorer.py`(outliers 数量 → score;可能简化为单子检测无需 scorer 合成)

**备选:**
- **平铺在 Agent 文件内**:Agent 文件会过长,难测试 → 拒绝
- **合并 extractor + detector**:职责不清,C11 已证明分离利于 L1 单元测试 → 拒绝

**Rationale:** 复用 C11 模式降低心智负担;L1 单元测试可独立覆盖 extractor / detector / scorer;未来扩"标底路径"时 detector 加第二路方法即可,子包结构不变。

### D3:preflight 新增 `project_has_priced_bidders` helper

**选择:** 在 `_preflight_helpers.py` 新增:
```python
async def project_has_priced_bidders(
    session: AsyncSession,
    project_id: int,
    min_count: int = 3,
) -> bool:
    """项目下 parse_status='priced' 且有 price_items 的 bidder 数 >= min_count"""
```

**备选:**
- **内联到 Agent preflight**:重复查询逻辑,不便测试 → 拒绝
- **复用 C11 `bidder_has_priced` 循环调用**:N+1 查询,性能差 → 拒绝

**Rationale:** 独立 helper 一次 COUNT 查询;`min_count` 参数化便于 L1 mock;命名贴 C10 `bidder_has_metadata` / C11 `bidder_has_priced` 风格。

### D4:env 前缀 `PRICE_ANOMALY_*`,7 个变量

| env | 默认 | 说明 |
|---|---|---|
| `PRICE_ANOMALY_ENABLED` | `true` | Agent 总开关(disabled → 早返,不调 extractor) |
| `PRICE_ANOMALY_MIN_SAMPLE_SIZE` | `3` | 样本下限;< 此值 → Agent 级 skip 哨兵 |
| `PRICE_ANOMALY_DEVIATION_THRESHOLD` | `0.30` | 偏离阈值(0.30 = 30%) |
| `PRICE_ANOMALY_DIRECTION` | `low` | 偏离方向:`low` / `high` / `both`;本期仅实现 `low` |
| `PRICE_ANOMALY_BASELINE_ENABLED` | `false` | 标底路径总开关(本期硬 false) |
| `PRICE_ANOMALY_MAX_BIDDERS` | `50` | 每项目最多处理 bidder 数(防大项目爆炸) |
| `PRICE_ANOMALY_WEIGHT` | `1.0` | 此 Agent 在 judge 合成的权重占位(C14 可覆盖) |

**Rationale:** 与 C11 `PRICE_CONSISTENCY_*` 命名前缀平行;`BASELINE_ENABLED` 预留但本期硬 false,C12 代码读到非 false 应明确 WARN(防误配置);`DIRECTION` 预留 enum 但本期仅实现 `low` 分支(其他值 fallback 到 `low` + log warn)。

### D5:样本过滤策略

**选择:** 仅计 `parse_status='priced'` 且 `price_items` 非空的 bidder(`extractor.aggregate_bidder_totals` 内部 filter);parse 失败 / 未解析的 bidder 完全不计入样本。

**备选:**
- **全部算,缺报价当 0 处理**:会把"未解析"当"0 元报价",均值被强行拉低,其他家相对均值偏离全部失真 → 拒绝
- **缺报价按项目均值替代**:信息伪造,evidence 不可解释 → 拒绝

**Rationale:** 贴兜底原则(失败需对用户可解释);Agent 级 skip 哨兵 `score=0.0 + evidence.skip_reason="sample_size_below_min"` 已覆盖样本不足场景。

### D6:项目类型本期不区分

**选择:** 统一阈值 30%,所有项目走同一 `DEVIATION_THRESHOLD`;evidence 中不记录 project_type;实战数据反馈后作为 follow-up 加 `PRICE_ANOMALY_DEVIATION_THRESHOLD_<TYPE>` 覆盖层。

**Rationale:** 执行简单;M3 scope 收缩;若未来区分,env 覆盖或 config 表扩展即可,evidence 结构不变(只是阈值来源不同)。

### D7:evidence 结构(预留 follow-up 字段)

```json
{
  "algorithm": "price_anomaly_v1",
  "enabled": true,
  "sample_size": 5,
  "mean": 95.5,
  "outliers": [
    {
      "bidder_id": 42,
      "total_price": 70.0,
      "deviation": -0.266,
      "direction": "low"
    }
  ],
  "baseline": null,
  "llm_explanation": null,
  "config": {
    "min_sample_size": 3,
    "deviation_threshold": 0.30,
    "direction": "low"
  }
}
```

**skip 场景:**
```json
{
  "algorithm": "price_anomaly_v1",
  "enabled": true,
  "sample_size": 2,
  "mean": null,
  "outliers": [],
  "baseline": null,
  "llm_explanation": null,
  "skip_reason": "sample_size_below_min",
  "config": { ... }
}
```

**disabled 场景(`ENABLED=false`):**
```json
{
  "algorithm": "price_anomaly_v1",
  "enabled": false,
  "outliers": []
}
```

**Rationale:** `baseline: null` 给标底 follow-up 填字段;`llm_explanation: null` 给 C14 回填(或前端从 C14 OverallAnalysis 关联读);三态 `enabled / skip_reason / outliers` 语义清晰,UI 可分别渲染。

### D8:Agent 级 skip 哨兵语义(对齐 C11)

- `ENABLED=false` → score=0.0,enabled=false,outliers=[],早返不调 extractor
- sample_size < MIN_SAMPLE_SIZE → score=0.0,participating_subdims=[],skip_reason 填写
- extractor 返 0 bidder(所有 parse 失败)→ 同样走 sample_size < 3 路径

**Rationale:** 贴 C10/C11 既定哨兵语义,前端识别成本为零;`participating_subdims=[]` 复用(此 Agent 单子检测,但字段保留为 [] 或 ["mean"] 可选,选 [] 贴 C11 Agent 级 skip 约定)。

### D9:algorithm version = `price_anomaly_v1`

**Rationale:** 贴 C7~C11 版本号风格;未来加标底路径时升 v2。

## Risks / Trade-offs

- **[Risk] "全体围标偏低"场景漏报**:所有 bidder 都报低价时,均值也低,相对均值无人偏离,C12 全部不触发 → **Mitigation**:这正是标底路径(follow-up)解决的场景;本期 evidence 明确"基于均值判断",文档说明此局限;C14 LLM 综合研判可结合其他 Agent 信号(如 text_similarity 高 + 均值显著低于市场价)补齐
- **[Risk] 项目 bidder 数巨大(>50)性能**:`MAX_BIDDERS=50` 上限;实战若常态超过,作为 follow-up 调大或分块处理
- **[Risk] 极端值拉偏均值**:1 家报 1 元 + 4 家正常 → 均值被拉低 20%,其他家相对均值反而不偏 → **Mitigation**:本期接受此 trade-off(极端值本身会被告警);follow-up 升级为中位数 + IQR robust 法(贴 C11 series 子检测同类 follow-up)
- **[Risk] 项目类型不区分导致总包项目误报高**:总包报价综合性强,波动大,统一 30% 阈值可能对总包项目误报率偏高 → **Mitigation**:30% 已按"强可疑"档,总包项目实际偏离超 30% 仍属可疑;实战反馈后 follow-up 加 per-type 阈值
- **[Risk] 注册表从 10 → 11 破坏 C6 锁定契约**:C6 原 spec "10 Agent" 是硬约束,修改需 MODIFIED Requirement → **Mitigation**:spec MODIFIED 明确标注"C12 扩展至 11 Agent"场景,Scenario 对照写;前端若硬编码 10 需同步改(需 grep check)
- **[Trade-off] evidence `llm_explanation=null` 占位**:前端打开 evidence 面板会看到空字段,可能让用户困惑 → **Mitigation**:前端渲染时判断 null 则隐藏该字段,或显示"LLM 综合研判未完成"占位文案(UI 层处理,不在本 change scope)

## Migration Plan

**部署步骤:**
1. 合并本 change → 后端重启
2. 注册表加载期 `EXPECTED_AGENT_COUNT=11` 校验通过(registry 含 11 Agent)
3. 下次项目触发 detect 时,`price_anomaly` Agent 随 fan-out 执行;历史项目不回填(C12 检测是 per-run,不持久化全局信号)

**前端联动(如需):**
- 前端若硬编码 Agent 数 = 10(进度条/展示) → 需改为动态读 registry 或改为 11
- 本 change 不含前端改动,若 grep 发现硬编码会作为 follow-up cleanup

**rollback 策略:**
- env `PRICE_ANOMALY_ENABLED=false` → Agent 早返,dummy 般无副作用;evidence 空不阻塞 judge 合成(judge 对 score=0.0 天然容忍)
- 代码回滚:revert 本 change commit;registry `EXPECTED_AGENT_COUNT` 回到 10

## Open Questions

- 无硬阻塞;前端 Agent 数硬编码扫描作为 apply 阶段副产品处理
