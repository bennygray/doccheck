## Why

对比视图展示的相似段落 match 数量远少于检测实际发现的（DEF-004）。原因是检测时 evidence_json 中只保存 top-N 个 sample，对比视图依赖这些 sample 做高亮。当前 `_SAMPLES_LIMIT=10`（text_similarity）、`_CHAPTER_SAMPLES_LIMIT=5`（section_similarity），在段落对较多的项目中展示不充分。

## What Changes

- `text_sim_impl/aggregator.py`：`_SAMPLES_LIMIT` 从 10 调大到 30
- `section_sim_impl/scorer.py`：`_CHAPTER_SAMPLES_LIMIT` 从 5 调大到 15
- 折中方案：仅调参数，不引入实时计算。后续如需完整展示再升级为对比页独立计算（第二期 backlog）

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 spec 级变更，仅调整参数常量）

## Impact

- **后端代码**: 2 个文件各改 1 个常量
- **存储**: evidence_json 体积略增（每条 sample 约 200 字，增加 20 条 ≈ 4KB/pair）
- **性能**: 无影响（sample 截取是内存操作）
