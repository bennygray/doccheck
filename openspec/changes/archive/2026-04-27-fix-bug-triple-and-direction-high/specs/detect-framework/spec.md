## ADDED Requirements

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
