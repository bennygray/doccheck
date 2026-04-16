## 1. Global agent early-return 分支修复

- [x] 1.1 [impl] `error_consistency.py`: early-return 分支(bidders<2)补写 OA 行(score=0, evidence 含 skip_reason)
- [x] 1.2 [impl] `image_reuse.py`: 有 session 但数据不足时补写 OA 行(score=0, evidence 含 skip_reason)

## 2. Judge 阶段 pair 类维度 OA 写入

- [x] 2.1 [impl] `judge.py` 的 `judge_and_create_report()`: 在 AnalysisReport INSERT 前,对 7 个 pair 维度写入 OA 聚合行(score=per_dim_max, evidence_json 含 source/best_score/has_iron_evidence/pair_count/ironclad_pair_count)
- [x] 2.2 [impl] OA 写入幂等保护: 先查 `(project_id, version, dimension)` 是否已有 OA 行,有则跳过

## 3. 测试

- [x] 3.1 [L1] judge.py 单元测试: 验证 judge_and_create_report 后 overall_analyses 表有 11 行(4 global + 7 pair)
- [x] 3.2 [L1] judge.py 单元测试: 验证 pair 类 OA 行 evidence_json 结构正确(source/best_score/has_iron_evidence/pair_count/ironclad_pair_count)
- [x] 3.3 [L1] judge.py 单元测试: 验证重复调用幂等(OA 行不重复)
- [x] 3.4 [L1] error_consistency 单元测试: bidders<2 时仍写 OA(score=0, skip_reason)
- [x] 3.5 [L1] image_reuse 单元测试: 有 session 但无图片时仍写 OA(score=0, skip_reason)
- [x] 3.6 [L2] E2E API 测试: 完整检测流程后,维度级复核 API 对全部 11 维度返回 200
- [x] 3.7 [L1][L2] 跑全部 L1 + L2 测试,全绿 (L1: 801 passed, L2: 250 passed)
