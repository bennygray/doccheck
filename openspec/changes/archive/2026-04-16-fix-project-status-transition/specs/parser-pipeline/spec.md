## MODIFIED Requirements

### Requirement: per-bidder 流水线完成后触发项目状态聚合

per-bidder 解析流水线（`run_pipeline`）在 bidder 到达终态后，SHALL 调用项目状态聚合逻辑，检查是否所有同项目 bidder 均已终态，若是则触发 `project.status` 流转。

#### Scenario: bidder 到达 identified 终态
- **WHEN** `run_pipeline()` 将 bidder 状态设为 `identified`（角色分类完成，无报价 XLSX）
- **THEN** 调用项目状态聚合函数，检查同项目其他 bidder 状态

#### Scenario: bidder 到达 priced 终态
- **WHEN** `run_pipeline()` 将 bidder 状态设为 `priced`（报价提取完成）
- **THEN** 调用项目状态聚合函数

#### Scenario: bidder 解析失败
- **WHEN** `run_pipeline()` 将 bidder 状态设为 `identify_failed` 或 `price_failed`
- **THEN** 同样调用项目状态聚合函数（失败也是终态）
