## Why

维度级复核 API（AT-9.2）对全部 11 个维度均返回 404 "维度无 OA 记录"。根因：7 个 pair 类 agent 只写 `pair_comparisons`，不写 `overall_analyses`；复核 API 要求 OA 行存在才能写入复核标记。导致维度级精细化复核功能完全不可用，影响审计合规完整性。

## What Changes

- **pair 类 agent 补写 OA 聚合行**：7 个 pair 类 agent（text_similarity / section_similarity / structure_similarity / metadata_author / metadata_time / metadata_machine / price_consistency）在 run() 完成后，聚合 pair_comparisons 结果写入一行 `overall_analyses` 记录（best_score + 铁证汇总 + evidence 摘要）
- **global 类 agent 补全遗漏分支**：error_consistency 和 image_reuse 在 early-return 分支（session=None / bidders<2）也写入 OA 行（score=0 + skip_reason），与 style agent 的做法对齐
- **judge.py 适配**：judge 当前临时计算 pair 维度的 best_score 和 is_ironclad，改为优先读 OA 行的持久化值（OA 成为所有维度的统一数据源）

## Capabilities

### New Capabilities

（无新增能力）

### Modified Capabilities

- `detect-framework`: pair 类 agent 新增写 OA 行的要求；judge 改为从 OA 统一读取维度结论

## Impact

- **后端 agent 代码**：7 个 pair agent + 2 个 global agent（error_consistency / image_reuse）的 run() 函数
- **judge.py**：report 生成逻辑从"临时聚合 pair_comparisons"改为"读 overall_analyses"
- **数据库**：`overall_analyses` 表行数从 ~4 行/版本增长到 11 行/版本（无 schema 变更）
- **API**：无接口变更；复核 API 无需改动，OA 行存在后自然可用
