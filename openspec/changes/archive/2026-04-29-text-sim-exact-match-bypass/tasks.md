## 1. 后端实施

- [x] [impl] `tfidf.py` 加 `_normalize(text)` 函数(D1: NFKC + `\s+` 合并 + strip)
- [x] [impl] `tfidf.py` 加 `_hash_pairs(paras_a, paras_b) -> (hits, hit_set)` 函数(D2+D3: sha1 hash + 笛卡尔积命中)
- [x] [impl] `tfidf.compute_pair_similarity` 入口集成 hash 旁路:hits 直接进结果集, cosine 矩阵 enumerate 时 `(i,j) in hit_set` 跳过(D4)
- [x] [impl] `config.py` `TEXT_SIM_MAX_PAIRS_TO_LLM` 默认值 30 → 80
- [x] [impl] `aggregator.py` `_SAMPLES_LIMIT` 30 → 80
- [x] [impl] `aggregator.build_evidence_json` 加 `pairs_exact_match` 字段 + `samples.label` 支持 `'exact_match'` 取值
- [x] [impl] `aggregator.compute_is_ironclad` 改自包含完整规则: `pairs_plagiarism ≥ 3` 或 占比 ≥ 50% 或 含 ≥ 1 段归一化长度 ≥ 50 的 exact_match → True;降级模式 MUST 永远 False(D8)
- [x] [impl] `models.ParaPair` 加可选 `match_kind: str | None` 字段(默认 None, hash 命中时 `'exact_match'`)
- [x] [impl] `llm_judge.call_llm_judge` 调用前加 `_estimate_prompt_tokens(pairs)` + 24K 溢出按 sim 降序 truncate;truncate 时 `evidence_json.degraded_reason = 'token_overflow'`(D5)
- [x] [impl] 测试遗留兜底:`backend/tests/unit/services/detect/agents/text_sim_impl/test_aggregator.py:137` 断言 `len(samples) == 30` 同步改 `== 80`
- [x] [impl] 前端 `CompareView.tsx` (或同等组件) 加 `sample.label || 'generic'` 旧 evidence label fallback(D7)

## 2. 单元测试 [L1]

- [x] [L1] hash 旁路命中单测:用客户 demo 三段(47 / 131 / 165 字)做 fixture, 全部命中 sim = 1.0, label = 'exact_match'
- [x] [L1] `_normalize` 等价性单测三组:(a) 全角半角逗号 NFKC; (b) `施工  方案` 双空格 vs 单空格; (c) 首尾换行 strip
- [x] [L1] ironclad 长度门槛边界:(a) 49 字 exact_match 不升铁证; (b) 50 字 exact_match 升铁证; (c) 降级模式 + 50 字 exact_match 仍不升铁证(MUST False)
- [x] [L1] cosine 候选集排除已 hash 命中对:验证 hash 命中的 (i, j) MUST NOT 出现在 LLM 输入 pairs 列表
- [x] [L1] label 互斥优先级:hash 命中段 label MUST NOT 被 LLM judge 二次覆写
- [x] [L1] cap 30 → 80 不影响 ironclad 算分公式:同 fixture 旧 cap 30 与新 cap 80 算出 score 一致
- [x] [L1] LLM token 溢出 truncate 单测:模拟 prompt > 24K, 验证按 sim 降序保留, evidence.degraded_reason = 'token_overflow'

## 3. API 级 E2E [L2]

- [x] [L2] `text_similarity` agent 端到端:hash 命中段进 evidence top + 同 (a_idx, b_idx) 对 MUST NOT 进 LLM judge prompt
- [x] [L2] evidence_json schema 兼容:模拟旧版本无 `pairs_exact_match` 字段, reports API 返回 200 不抛错
- [x] [L2] PairComparison.version 递增正确:同项目重跑后 max(version) = N+1, reports API 按 max version 取数链路通

## 4. UI 级 E2E [L3]

- [x] [L3] **走真 LLM**(本 change 选真 LLM, 参考 CLAUDE.md "L3 LLM mock 约定: 真 LLM 调用 ... 由 change 自己选";真 LLM 不入 CI 自动化, 由 Claude 在 session 内 Claude_in_Chrome 驱动手工执行 + 截图):

  用本地 `project_id=3296` + `bidder A=3720 / C=3721` 重传 `tmp_repro2/同样句式加在第一段/` 三家 zip(或仅 A、C 两家),启动新检测得 `version=2`,凭证落 `e2e/artifacts/text-sim-exact-match-bypass-2026-04-29/`:

  - (a) 报告页双栏对比 UI 三段(47 / 131 / 165 字)全部高亮显示
  - (b) 原 28 对真模板段 plagiarism / template 判定不变(回归保护截图)
  - (c) `evidence_json.pairs_exact_match ≥ 3`(API 直接 dump JSON 截图)
  - (d) `is_ironclad = True`(因含 ≥ 1 段 ≥ 50 字 exact_match)
  - (e) `README.md` 含期望 vs 实际、commit hash、关键路径截图说明

## 5. 文档与归档 [manual]

- [x] [manual] 归档前 `docs/handoff.md` "演进路径"段记入: 本 change 仅救 100% 字符复制,改 1 字近似抄袭由 ngram / MinHash / shingle v2 路径处理(reviewer Round 2 第 4 条承诺)
- [x] [manual] 客户演示场景人工验收: 复制 demo 用例三段(47 / 131 / 165 字)肉眼可见高亮,且 UI score 提升合理(向用户解释新版本算法 v2 vs 历史 v1 的区别)

## 6. 总汇任务

- [x] 跑 [L1][L2][L3] 全部测试, 全绿(L3 真 LLM 由 Claude 在 session 内手工执行,凭证齐全视为通过)
