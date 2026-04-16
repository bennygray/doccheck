## Context

维度级复核 API（`reviews.py`）查询 `overall_analyses` 表获取 OA 行，写入 `manual_review_json`。当前只有 4 个 global 类 agent 写 OA，7 个 pair 类 agent 只写 `pair_comparisons`。judge.py 在生成报告时临时聚合 pair_comparisons 计算 best_score 和 is_ironclad，未持久化到 OA。

现有 helper：`anomaly_impl/__init__.py` 的 `write_overall_analysis_row()` 已被 global agent 使用。

## Goals / Non-Goals

**Goals:**
- 检测完成后 `overall_analyses` 表包含全部 11 个维度的行（每版本 11 行）
- 维度级复核 API 对所有维度可用，无需任何 API 侧改动
- OA 行成为所有维度的统一数据源（score + evidence + 复核标记）

**Non-Goals:**
- 不改 `pair_comparisons` 表结构或写入逻辑
- 不改复核 API（`reviews.py`）代码
- 不改报告页面前端
- 不做 OA 行的数据回填（已有的历史检测版本不补）

## Decisions

### D1: OA 写入时机——agent 内部 vs judge 阶段

**选择：judge 阶段统一写入 pair 类维度的 OA 行**

替代方案：在每个 pair agent 的 run() 里聚合并写 OA。

选 judge 的原因：
- pair agent 只看单个 pair（bidder_a vs bidder_b），不知道全局 best_score；聚合逻辑已在 judge 的 `_compute_dims_and_iron()` 里实现
- 7 个 agent 各自写一遍聚合逻辑 = 7 处重复代码 + 7 处可能的不一致
- judge 是所有 pair/global 结果的唯一汇合点，此处写 OA 天然保证数据一致

### D2: global agent 遗漏分支的修复方式

**选择：在 error_consistency 和 image_reuse 的 early-return 分支补写 OA 行（score=0, evidence 含 skip_reason）**

对齐 style agent 现有做法（已有注释"仍写一行 OA 让前端可见 skip 原因"）。

### D3: judge.py 中 pair 维度 OA 的 evidence_json 内容

OA 行的 evidence_json 存聚合摘要：
```json
{
  "source": "pair_aggregation",
  "best_score": 100.0,
  "has_iron_evidence": true,
  "pair_count": 1,
  "ironclad_pair_count": 1
}
```

不复制 pair 级详细 evidence（已在 pair_comparisons 里），只存聚合统计。复核人点进维度详情看到的仍是 pair_comparisons 的明细。

### D4: 写入顺序和幂等

judge_and_create_report 已有幂等检查（AnalysisReport 存在则跳过）。OA 写入放在 AnalysisReport INSERT 之前，同一事务内。若重跑 judge，pair 类 OA 行也受幂等保护（先查后写）。

## Risks / Trade-offs

- **[数据冗余]** pair 维度的 best_score 同时存在于 OA 行和可从 pair_comparisons 计算得出 → 可接受：OA 行是"维度级结论"的 canonical 存储，pair_comparisons 是"明细证据"
- **[历史数据]** 已有检测版本不补 OA → 旧版本的维度级复核仍返回 404 → 可接受：用户重跑检测即可；不做数据迁移避免复杂度
- **[事务内写入量增加]** 从 ~4 行 OA 增加到 11 行 → 增量极小，无性能风险
