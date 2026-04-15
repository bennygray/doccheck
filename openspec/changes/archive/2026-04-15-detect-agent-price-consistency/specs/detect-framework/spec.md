## MODIFIED Requirements

### Requirement: 10 Agent 骨架文件与 dummy run

后端 MUST 在 `app/services/detect/agents/` 下提供 10 个文件,每个文件定义一个 Agent 骨架,通过 `@register_agent` 装饰器注册到 AGENT_REGISTRY。

C11 归档后,Agent `text_similarity`(C7)、`section_similarity`(C8)、`structure_similarity`(C9)、`metadata_author` / `metadata_time` / `metadata_machine`(C10)、`price_consistency`(C11)的 `run()` 已替换为真实算法,不再走 dummy;其余 3 个 Agent(`error_consistency / style / image_reuse`)`run()` 继续走 dummy,直至 C12~C13 各自替换。

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

C12~C13 各 change 替换对应 `run()` 实现,不改 preflight、不改文件名、不改注册 key。

**注意**:C11 归档后,7 个 pair 型 Agent 的 `run()` 全部已替换为真实算法;dummy 列表仅剩 3 个 global 型 Agent(`error_consistency / style / image_reuse`)。

#### Scenario: 10 Agent 模块加载后注册表完整

- **WHEN** `from app.services.detect import agents` 触发所有 agents 模块加载
- **THEN** `AGENT_REGISTRY` 含 10 条目;每条 `run` 可调

#### Scenario: dummy run 产生 OverallAnalysis 行

- **WHEN** 调 style dummy run(global 型,C11 后仍为 dummy)
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

#### Scenario: price_consistency 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["price_consistency"].run(ctx)` 且双方 PriceItem 存在
- **THEN** `evidence_json["algorithm"] == "price_consistency_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

## ADDED Requirements

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
