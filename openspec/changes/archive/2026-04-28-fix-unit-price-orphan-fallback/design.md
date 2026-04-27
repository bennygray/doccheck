## Context

**当前状态**:
- `run_pipeline` 阶段 3(报价阶段)用 `_find_pricing_xlsx(bidder_id)` 选规则识别样本(leader 选举)和 `_find_all_pricing_xlsx(bidder_id)` 选回填样本
- 两个查询都是固定条件 `where file_role == 'pricing' AND parse_status == 'identified' AND file_type == '.xlsx'`
- `unit_price` 角色枚举存在但下游 0 消费,是设计孤儿(C5 parser-pipeline 时分立,后续 OpenSpec 未赋予处理路径)

**问题触发**:
- 服务器生产环境用 DeepSeek `deepseek-v4-flash`;监理报价 xlsx 首段含"委托监理综合单价报价表"等"综合单价"字样
- LLM 在"分类成功但答案错误"路径返回 `file_role='unit_price' confidence='high'` → 通过 prompt 返回 valid JSON,无规则兜底拦截
- 该 bidder 在 `_find_pricing_xlsx` 查询返空 → run_pipeline 第 112-115 行的"无报价表 → identified 即终态"分支命中 → silent failure

**约束**:
- 不能改 LLM prompt(F 维度调查显示 prompt 工程不可靠;模型升级会回归)
- 不能强制本地与生产 LLM 一致(超出本 change 范围;在 handoff 留 future work)
- 不能引入新 DB 字段(避免迁移代价)
- 必须保护下游 4 个 price 系列 detector(尤其今天新增的 `price_overshoot` / `price_total_match` 铁证级)不被"主表+子表混算"污染

**利益相关方**:
- 产品/业务(用户):监理类项目能正常出报告,不再 silent failure
- 检测算法(detector agents):upstream 数据语义不变(单 bidder 仍是单源 price_items)

## Goals / Non-Goals

**Goals:**
- 解决"LLM 误判 unit_price 导致 silent failure"这一具体 bug
- 不引入"主表+子表混算"风险(单 bidder 单类不变量)
- 改动最小化(2 个 helper 函数 + 测试)
- 行为对"已正确判 pricing 的 bidder"零影响(主路径不变)

**Non-Goals:**
- 不解决 LLM 跨模型一致性根问题(单独立 change)
- 不让 `unit_price` 角色获得"独立的下游处理路径"(它仍是 fallback,不是一等公民)
- 不引入"项目级 role 一致化"(若 B 判 pricing、A/C 判 unit_price 各用各的;不强制统一)
- 不修复 `aggregate_bidder_totals` 不分桶问题(那是另一个 change 的事)
- 不改 prompt / 不改 role 枚举 / 不改 admin UI

## Decisions

### Decision 1:Fallback 分支语义采用 "elif" 而非 "union"

**选择**:`if pricing_xlsx_exists: return pricing; elif unit_price_xlsx_exists: return unit_price; else: return []`

**否决**:`return pricing_xlsx UNION unit_price_xlsx`(同时取两类)

**理由**:
- "Union 取两类"会让单 bidder 的 `price_items` 来源跨越两份 xlsx → `aggregate_bidder_totals(SUM(total_price))` 在主表 + 子单价表共存场景重复求和
- 今天新增的 `price_overshoot`(铁证升 high)直接吃这个 SUM 结果 → 误报后无法逆转
- "elif 互斥"天然实现"单 bidder 单类不变量",无需额外强制代码

**下游消费方矩阵**(不变量保护范围逐一列证):

| # | 消费方 | 文件 | 取数方式 | elif 不变量是否必要 |
|---|---|---|---|---|
| ① | `aggregate_bidder_totals` | `anomaly_impl/extractor.py:40` | `SUM(total_price) GROUP BY bidder_id`,不分 sheet/role | ✅ 必要(直接 SUM 翻倍源) |
| ② | `price_overshoot`(铁证) | `agents/price_overshoot.py` | 吃 ① 的输出判 `total > max_price` | ✅ 必要(误报直接升 high) |
| ③ | `price_total_match`(铁证) | `agents/price_total_match.py` | 吃 ① 的输出判两两相等 | ✅ 必要(误报/假阴都靠不变量保护) |
| ④ | `fill_price_from_rule` | `pipeline/fill_price.py` | 按 sheet_name + column_mapping 抽行 | ✅ 必要(主表 column 套子表会全行 None,数据虽不污染但产生噪音 partial_failed) |
| ⑤ | `text_sim_impl/segmenter` | `segmenter.py:25` | `ROLE_PRIORITY` 排除 pricing/unit_price | ⚪ 不受影响(与价格无关) |
| ⑥ | `compare/metadata` | `routes/compare.py:469` | `_META_ROLE_PRIORITY` 排除 pricing/unit_price | ⚪ 不受影响 |
| ⑦ | `template_cluster` | `template_cluster.py:35` | `TEMPLATE_FILE_ROLES` 一视同仁含两者 | ⚪ 不受影响(消费 file_role 字段,与 price_items 解耦) |

①-④ 共同要求"单 bidder 单类"才不会被混算污染;⑤-⑦ 与本 change 无关。

### Decision 2:Fallback 在 `_find_pricing_xlsx`(leader 选举)与 `_find_all_pricing_xlsx`(回填)两处对称处理

**选择**:两个 helper 函数对称加 fallback 逻辑

**否决**:仅在回填阶段加 fallback(leader 选举仍只认 pricing)

**理由**:
- 若仅回填加 fallback、leader 选举不加:项目内全部 bidder 都被判 `unit_price` 时,无 leader 选出 → `acquire_or_wait_rule` 无法触发 LLM rule detection → 整个项目卡死
- 必须让 leader 选举也能 fallback 到 unit_price 类 xlsx,才能触发 LLM 识别 sheets_config

### Decision 3:Fallback 不修改 SQL 一次性 IN 查询,改为顺序两次查询

**选择**:Python 层先查 pricing,空时再查 unit_price

**否决**:`where file_role IN ('pricing', 'unit_price') ORDER BY CASE WHEN file_role='pricing' THEN 0 ELSE 1 END`

**理由**:
- 顺序两次查询的"互斥"语义清晰:第一次有结果就直接 return,不会触碰 unit_price
- IN + ORDER BY CASE 写法正确性也成立但语义混在一行 SQL 里,后续维护者难辨"是否会同时取两类"
- 性能差异忽略:bidder 的 xlsx 数通常 ≤ 5 行,两次 SELECT 无性能影响

### Decision 4:不引入"项目级 role 一致化"

**选择**:每 bidder 独立判定(B 用 pricing 数据、A 用 unit_price 数据)

**否决**:看项目内 role 分布,选多数派或统一 fallback

**理由**:
- 当前症状下底层 xlsx 内容结构相同(都是"委托监理综合单价报价表"),数据可比
- 项目级一致化会引入复杂状态(投票/共识)且改动面大
- 真正的"不同源数据不可比"问题应由 cross-model 一致性 change 解决,不在本次范围

### Decision 5:不在前端 UI 增加"该 bidder 走了 fallback"提示

**选择**:fallback 对前端透明,price_items 数据正常展示

**否决**:在前端展示"⚠️ unit_price fallback"角标提醒用户审核

**理由**:
- 用户的核心诉求是"看到价格数据",不是"理解 role 误判内幕"
- 增加角标会让产品概念面变大(用户得理解 pricing vs unit_price 的区别)
- 若未来 cross-model 一致性 change 让 LLM 直接判对,此前的 fallback 标记会成噪声

## Risks / Trade-offs

**[Risk] 项目内不同 bidder 落到不同 role,数据严格意义不同源**
→ 缓解:本案监理场景底层 xlsx 内容结构完全相同,price_consistency / price_overshoot 等检测的可比性实际成立;若未来出现"B 是真实主报价表 + A 是真实子单价表"这种异构,需后续 cross-model 一致性 change 解决。本 change 不引入回归(原行为是 silent failure,现行为是"次优数据有结果"),净改善

**[Risk] 同一 bidder 同时上传主报价表 + 子单价表两份 xlsx,fallback 优先 pricing,unit_price 子表被丢弃**
→ 缓解:与本 change 之前的现状一致;子单价表本来就被丢弃,fallback 没有改变这个行为;若未来要支持子单价表,加 `price_items.source_role` 字段单独立 change

**[Risk] LLM 把真正的子单价表判成 pricing,fallback 不会触发但回填后污染 price_items 源**
→ 缓解:这是 LLM 误判另一个方向的问题(把 unit_price 判成 pricing),不在本 change 范围;同样需 cross-model 一致性 change

**[Risk] L2 测试 fixture 难造"3 家全 unit_price"场景**
→ 缓解:不真的跑 LLM,直接 mock `classify_bidder` 让所有 xlsx 落 `file_role='unit_price'`;真实端到端验证靠 L3 用 Claude_in_Chrome 上传同样 zip 走 UI

**[Trade-off] 不修 `aggregate_bidder_totals` 的"不分桶 SUM" bug**
→ 接受:那个问题需要"按 sheet 分桶或按 source 分桶"的更大重构,与本 change 不绑;本 change 通过"单 bidder 单类不变量"绕过它

## Migration Plan

**部署**:
- 无 DB migration,无 alembic 脚本
- 上线即生效;已经存在的 `identified` 终态 bidder(被 unit_price 误判卡住的)需用户手工 `re-parse` 触发 pipeline 重跑(re-parse 端点已存在)

**回滚**:
- 把两个 helper 函数改回 `where file_role == 'pricing'` 单条件即可
- 已用 fallback 写入的 `price_items` 不需要清理(数据本身正确,只是来源是 unit_price 类 xlsx;不影响下游)

**Future Work(在 handoff.md 记录)**:
1. **Cross-model 一致性**:本地补 DeepSeek 回归通道 + 高敏 LLM 调用点的 confidence 阈值拦截(role 分类 / price_rule / error_l5 铁证 / text_sim 定性)
2. **`unit_price` 角色定位决议**:要么真正赋予下游处理(如对比子单价表本身的相似度),要么从 9 角色枚举里彻底删除——目前的"标记但孤儿"是技术债
3. **`aggregate_bidder_totals` 分桶**:按 sheet 或按 source 分桶,根本性消除"主表+子表混算"风险
