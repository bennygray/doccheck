## Why

服务器生产环境 LLM(DeepSeek `deepseek-v4-flash`)对监理/咨询/服务类项目的报价 xlsx 误判 `file_role='unit_price'`(因首段含"综合单价"四字),而 `unit_price` 角色在下游报价回填管线 0 消费 → 该 bidder 卡在 `identified` 终态、`price_items=0`、UI 显示空白报价。本地火山 ark 模型不复现,但服务器 100% 复现且未来"综合单价"是行业惯例会反复触发。

最近新增的 `price_overshoot` / `price_total_match` 两个铁证级 detector 直接吃 `aggregate_bidder_totals(SUM(total_price))`——若让 `unit_price` 类 xlsx 也回填但与 `pricing` 类混算,会触发"主表+子表重复求和"导致铁证误报(强制升 `risk=high`)。所以兜底必须带"单 bidder 不混合"不变量。

**为什么不直接把 `unit_price` aliased 成 `pricing` 入库**:1) 保留原始 LLM 判定结果作为排查证据(future cross-model 一致性 change 需要这些样本);2) `template_cluster` 等下游已经独立消费 `unit_price` 角色,改写入会引入更大的语义破坏面。本 change 选择仅在"报价回填的 XLSX 选取"这一窄路径做兜底,`file_role` 字段忠实记录 LLM 原始输出。

## What Changes

- **`parser-pipeline` 报价阶段 xlsx 选取规则**:
  - 当前:仅选 `file_role='pricing'` 的 xlsx 进入规则识别 + 回填;`file_role='unit_price'` 的 xlsx 完全被忽略(silent failure)
  - 变更后:**按 bidder 逐个决策**——优先选 `pricing`;该 bidder 没有 `pricing` 类 xlsx 时,fallback 选 `unit_price`(仅 `parse_status='identified'` 的)
  - **不变量**:同一 bidder **永不同时混合** `pricing` 与 `unit_price` 两类(三分支互斥实现)
- 影响 `_find_pricing_xlsx`(leader 选举)和 `_find_all_pricing_xlsx`(回填遍历)两个查询函数
- 不引入新 DB 字段 / 新表 / 新角色枚举 / 新 prompt
- `unit_price` 角色保留(前端 UI / template_cluster 模板簇白名单等现有消费方不变)

## Capabilities

### New Capabilities
(无)

### Modified Capabilities
- `parser-pipeline`: "报价规则识别"与"报价回填"两个 Requirement 的"待识别 xlsx 选取范围"行为变更——从"仅 pricing"改为"pricing 优先 + unit_price 兜底,单 bidder 不混合"

## Impact

**代码**:
- `backend/app/services/parser/pipeline/run_pipeline.py`:`_find_pricing_xlsx` + `_find_all_pricing_xlsx` 两个 helper 函数

**测试**:
- 新增 unit 测试覆盖 fallback 三分支(纯 pricing / 纯 unit_price / 两者都有时只取 pricing)
- 新增 e2e 回归 case:3 家 bidder 全 unit_price 角色,验证全部 priced + price_items 非空 + `aggregate_bidder_totals` 不重复求和

**不影响**:
- DB schema / Alembic migration(无)
- 前端 UI / API 路由(无)
- 任何 detector agent 的算法(无,仅改变其上游数据来源)
- prompt 与 LLM 调用(无)
- 其他 9 角色枚举的语义(无)

**风险**:
- 项目内不同 bidder 被 LLM 落到不同 role(B 判 pricing、A/C 判 unit_price)→ 数据源严格意义不同源;但底层 xlsx 内容结构相同时(本案监理报价场景)实际可比。彻底解决需 cross-model 一致性方案,不在本次范围
- 若同一 bidder 实际同时上传"主报价表 + 子单价分析表"两份 xlsx,fallback 优先 pricing,unit_price 子表仍被丢弃(与现状一致,不引入新行为)
