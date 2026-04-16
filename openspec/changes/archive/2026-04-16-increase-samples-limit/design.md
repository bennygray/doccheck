## Context

检测 agent 在 evidence_json 中保存 top-N 相似段落样本供对比视图展示。当前上限偏小，用户在对比页看到的 match 少于检测发现的。

## Goals / Non-Goals

**Goals:**
- 增大 sample 保存数量，让对比视图覆盖更多相似段落

**Non-Goals:**
- 不做对比页实时计算（第二期 backlog）
- 不改对比 API 逻辑

## Decisions

### D1: text_similarity 从 10 → 30

实际项目中技术标段落数通常 100~500，高相似对不超过 50。30 条覆盖绝大多数场景。

### D2: section_similarity 从 5 → 15

章节级样本粒度更粗，15 条足够覆盖章节对比需求。
