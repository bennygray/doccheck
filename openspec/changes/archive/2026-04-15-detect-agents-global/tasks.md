## 1. error_impl 子包搭建

- [x] 1.1 [impl] 建目录 `backend/app/services/detect/agents/error_impl/` + `__init__.py`(共享 `_shape_subdim` helper,贴 C11/C12 evidence enabled 三态模式)
- [x] 1.2 [impl] 编写 `error_impl/config.py`:`ErrorConsistencyConfig` dataclass + 5 env 加载 + `load_config()` + 关键参数(MAX_CANDIDATE_SEGMENTS / MIN_KEYWORD_LEN)非法值 ValueError + 次要参数(LLM_TIMEOUT_S / LLM_MAX_RETRIES)warn fallback
- [x] 1.3 [impl] 编写 `error_impl/models.py`:`SuspiciousSegment / KeywordHit / LLMJudgment / DetectionResult` 4 个 TypedDict
- [x] 1.4 [impl] 编写 `error_impl/keyword_extractor.py`:`extract_keywords(bidder, downgrade=False) -> list[str]`(4 类字段平铺 + 短词过滤 + NFKC 归一化 + 去重 + downgrade 退化为 [bidder.name])
- [x] 1.5 [impl] 编写 `error_impl/intersect_searcher.py`:`async def search(session, bidder_a, bidder_b, kw_a, kw_b, cfg) -> list[SuspiciousSegment]`(双向 + paragraphs+header_footer 并集 + MAX_CANDIDATE_SEGMENTS 截断按 matched_keywords 数倒序)
- [x] 1.6 [impl] 编写 `error_impl/llm_judge.py`:`async def call_l5(segments, bidder_a, bidder_b, cfg) -> LLMJudgment`(走 llm_mock fixture / 真 LLM provider + 重试 + JSON 解析容错)
- [x] 1.7 [impl] 编写 `error_impl/scorer.py`:`compute_score(hits, llm_judgment) -> float`(占位公式 `min(100, hit_count*20 + 40 if direct_evidence else 0 + confidence*20 if is_cross_contamination)`)

## 2. image_impl 子包搭建

- [x] 2.1 [impl] 建目录 `backend/app/services/detect/agents/image_impl/` + `__init__.py`
- [x] 2.2 [impl] 编写 `image_impl/config.py`:`ImageReuseConfig` dataclass + 5 env 加载 + 关键参数(PHASH_DISTANCE_THRESHOLD 0~64 / MIN_WIDTH / MIN_HEIGHT)严格校验 + MAX_PAIRS warn fallback
- [x] 2.3 [impl] 编写 `image_impl/models.py`:`MD5Match / PHashMatch / DetectionResult` TypedDict
- [x] 2.4 [impl] 编写 `image_impl/hamming_comparator.py`:`async def compare(session, project_id, cfg) -> DetectionResult`(SQL WHERE 过滤小图 + MD5 INNER JOIN + pHash `imagehash.hex_to_hash().__sub__` 比较 + 去重 + MAX_PAIRS 截断)
- [x] 2.5 [impl] 编写 `image_impl/scorer.py`:占位公式 `min(100, md5_count * 30 + sum(phash_strength) * 10)`

## 3. style_impl 子包搭建

- [x] 3.1 [impl] 建目录 `backend/app/services/detect/agents/style_impl/` + `__init__.py`
- [x] 3.2 [impl] 编写 `style_impl/config.py`:`StyleConfig` dataclass + 6 env 加载 + 关键参数(GROUP_THRESHOLD / SAMPLE_PER_BIDDER 5~10 区间)严格校验 + 次要参数(TFIDF_FILTER_RATIO / LLM_TIMEOUT_S / LLM_MAX_RETRIES)warn fallback
- [x] 3.3 [impl] 编写 `style_impl/models.py`:`StyleFeatureBrief / GlobalComparison / DetectionResult` TypedDict
- [x] 3.4 [impl] 编写 `style_impl/sampler.py`:`async def sample(session, bidder_id, cfg) -> list[str]`(读 technical 角色文档段落 + TfidfVectorizer + IDF 过滤低 30% + 长度过滤 100~300 字 + 均匀抽样 SAMPLE_PER_BIDDER 段 + insufficient_sample 标记)
- [x] 3.5 [impl] 编写 `style_impl/llm_client.py`:`async def call_l8_stage1(bidder_id, paragraphs, cfg) -> StyleFeatureBrief` + `async def call_l8_stage2(briefs, cfg) -> GlobalComparison`(走 llm_mock fixture + 重试 + JSON 解析容错 + simulate_failure 测试钩子)
- [x] 3.6 [impl] 编写 `style_impl/scorer.py`:占位公式 `min(100, len(consistent_groups) * 30 + max(group.consistency_score) * 50)`;evidence.limitation_note 固定文案

## 4. preflight helper 扩展

- [x] 4.1 [impl] `_preflight_helpers.py` 新增 `def bidder_has_identity_info(bidder) -> bool`(同步函数,纯属性判断 + None / 非 dict / 空 dict 全返 False)
- [x] 4.2 [impl] `agents/error_consistency.py::preflight` 改用新 helper + 全部缺 → downgrade / 部分缺 → ok / 全有 → ok 三分支语义

## 5. 三 Agent 文件 run() 重写

- [x] 5.1 [impl] `agents/error_consistency.py::run()` 重写:5 层兜底(ENABLED=false 早返 / preflight downgrade 标记走降级 + 仍调 L-5 / 无可抽关键词 skip 哨兵 / L-5 LLM 失败仅展示程序 evidence 不铁证 / L-5 返 direct_evidence=true → is_iron_evidence=True);写 PairComparison 行(贴 spec §F-DA-02 "两两比对");evidence_json 按 spec schema 完整填(含 algorithm_version / downgrade_mode / llm_failed / llm_explanation:null 占位)
- [x] 5.2 [impl] `agents/image_reuse.py::run()` 重写:3 层兜底(ENABLED=false 早返 / 小图过滤后 0 张 skip 哨兵 / MD5+pHash 双路正常);写 OverallAnalysis 行(global 型,用 `write_overall_analysis_row` helper);evidence_json 按 spec schema 完整填(含 llm_non_generic_judgment:null 占位)
- [x] 5.3 [impl] `agents/style.py::run()` 重写:4 层兜底(ENABLED=false 早返 / preflight skip / Stage1 失败 skip 哨兵 / Stage2 失败 skip 哨兵 / >20 自动分组);写 OverallAnalysis 行;evidence_json 完整填(含 grouping_strategy / limitation_note)
- [x] 5.4 [impl] 三 Agent 异常路径:任意子模块抛异常 → catch + evidence.error 写入 + AgentTask 仍 succeeded(贴 C11/C12 异常语义)

## 6. llm_mock.py 扩展

- [x] 6.1 [impl] `tests/fixtures/llm_mock.py` 扩 `MOCK_L5_RESPONSES` + `mock_call_llm_l5(segments, bidder_a, bidder_b, *, simulate_failure=False) -> LLMJudgment`(支持 key 派生 + simulate_failure 抛 LLMCallError)
- [x] 6.2 [impl] `llm_mock.py` 扩 `MOCK_L8_STAGE1_RESPONSES` + `mock_call_l8_stage1(bidder_id, paragraphs, *, simulate_failure=False) -> StyleFeatureBrief`
- [x] 6.3 [impl] `llm_mock.py` 扩 `MOCK_L8_STAGE2_RESPONSES` + `mock_call_l8_stage2(briefs, *, simulate_failure=False) -> GlobalComparison`
- [x] 6.4 [impl] 单一入口约束:测试通过 `monkeypatch.setattr(error_impl.llm_judge, "call_l5", mock_call_llm_l5)` 等方式注入,production 代码不分散 mock 逻辑

## 7. spec 文件中 dummy 列表清空更新

- [x] 7.1 [impl] `agents/__init__.py` 文件头注释更新("3 global Agent dummy" → "全部 11 Agent run() 已替换为真实算法,dummy 列表清空")
- [x] 7.2 [impl] 注释统一:三 Agent 文件头去 "C6 dummy" 标识

## 8. error_consistency L1 单元测试

- [x] 8.1 [L1] `tests/unit/test_error_consistency_config.py` ~10 用例:默认 / 5 env 覆盖 / 非法 MAX_CANDIDATE_SEGMENTS raise / 非法 MIN_KEYWORD_LEN raise / 非法 LLM_TIMEOUT_S warn fallback / 非法 LLM_MAX_RETRIES warn fallback
- [x] 8.2 [L1] `tests/unit/test_error_consistency_keyword_extractor.py` ~8 用例:正常 4 类字段 / 短词过滤 / downgrade 模式用 name / 空 identity_info 抛 / NFKC 归一化 / 去重 / 缺字段不报错 / 列表字段平铺
- [x] 8.3 [L1] `tests/unit/test_error_consistency_intersect_searcher.py` ~8 用例:双向命中 / paragraphs 命中 / header_footer 命中 / 双源合并 / 无命中返 [] / MAX_CANDIDATE_SEGMENTS 截断 / 截断后倒序按 matched_keywords 数 / 跨 doc_role 全检索
- [x] 8.4 [L1] `tests/unit/test_error_consistency_llm_judge.py` ~6 用例:mock 返铁证 / mock 返非铁证 / mock 返污染但非铁证 / simulate_failure 抛 LLMCallError / JSON 解析失败 / 重试机制
- [x] 8.5 [L1] `tests/unit/test_error_consistency_scorer.py` ~5 用例:0 hits / 多 hits / direct_evidence 加分 / is_cross_contamination 加分 / 100 上限
- [x] 8.6 [L1] `tests/unit/test_error_consistency_preflight.py` ~5 用例:全有 ok / 全缺 downgrade / 部分缺 ok / < 2 bidder skip / bidder_has_identity_info helper 三态
- [x] 8.7 [L1] `tests/unit/test_error_consistency_run.py` ~7 用例:disabled 早返 / 正常铁证命中 / 非铁证命中 / downgrade 模式不铁证 / L-5 失败仅展示关键词 / extractor 异常 / 无可抽关键词 skip 哨兵

## 9. image_reuse L1 单元测试

- [x] 9.1 [L1] `tests/unit/test_image_reuse_config.py` ~8 用例:默认 / PHASH_DISTANCE_THRESHOLD 0~64 边界 / 越界 raise / MIN_WIDTH/HEIGHT raise / MAX_PAIRS warn fallback / 各 env 覆盖
- [x] 9.2 [L1] `tests/unit/test_image_reuse_hamming_comparator.py` ~10 用例:MD5 命中 hit_strength=1.0 / pHash 距离 3 命中 / pHash 距离 6 不命中 / 小图过滤 / MD5 命中后不进 pHash / MAX_PAIRS 截断 / 跨 bidder 两两比 / 同 bidder 内不比 / 空图集合返空 / `imagehash.hex_to_hash` API 集成
- [x] 9.3 [L1] `tests/unit/test_image_reuse_scorer.py` ~5 用例:0 命中 / 1 MD5 / 多 pHash / 100 上限 / 混合 MD5+pHash
- [x] 9.4 [L1] `tests/unit/test_image_reuse_run.py` ~6 用例:disabled 早返 / 正常 MD5 命中 / 正常 pHash 命中 / 全部小图过滤后 skip 哨兵 / `is_iron_evidence` 强制 False / evidence.llm_non_generic_judgment=null 占位

## 10. style L1 单元测试

- [x] 10.1 [L1] `tests/unit/test_style_config.py` ~10 用例:默认 / GROUP_THRESHOLD 边界 / SAMPLE_PER_BIDDER 5~10 严格 / 越界 raise / TFIDF_FILTER_RATIO warn fallback / 各 env 覆盖
- [x] 10.2 [L1] `tests/unit/test_style_sampler.py` ~8 用例:正常抽样 / TF-IDF 过滤高频通用段落 / 长度过滤 100~300 / 均匀抽样 / 仅 technical 角色 / 段落不足标 insufficient_sample / 0 段落返 [] / 抽样数等于 SAMPLE_PER_BIDDER
- [x] 10.3 [L1] `tests/unit/test_style_llm_client.py` ~6 用例:Stage1 mock 正常 / Stage2 mock 正常 / Stage1 simulate_failure 抛 / Stage2 simulate_failure 抛 / JSON 解析失败 / 重试机制
- [x] 10.4 [L1] `tests/unit/test_style_scorer.py` ~5 用例:0 consistent_groups / 1 group 高分 / 多 groups / 100 上限 / limitation_note 字段固定
- [x] 10.5 [L1] `tests/unit/test_style_run.py` ~9 用例:disabled 早返 / 正常 Stage1+Stage2 / Stage1 失败 skip 哨兵 / Stage2 失败 skip 哨兵 / >20 自动分组 grouping_strategy=grouped / 单组 grouping_strategy=single / preflight skip / 单 bidder insufficient_sample / `is_iron_evidence` 始终 False

## 11. L2 API 级 E2E 测试

- [x] 11.1 [L2] `tests/e2e/test_detect_error_consistency_agent.py` Scenario 1:3 家 bidder 含 identity_info,mock L-5 返铁证 → PairComparison 1 行 is_ironclad=true,evidence.llm_judgment.direct_evidence=true
- [x] 11.2 [L2] Scenario 2:1 家 identity_info=None(其他 2 家有)→ preflight ok(部分缺允许),run 内部该 bidder 用 name 退化关键词
- [x] 11.3 [L2] Scenario 3:全部 identity_info=None → preflight downgrade,run 仍调 L-5 但 is_ironclad=false,evidence.downgrade_mode=true
- [x] 11.4 [L2] Scenario 4:env `ERROR_CONSISTENCY_ENABLED=false` → evidence.enabled=false
- [x] 11.5 [L2] `tests/e2e/test_detect_image_reuse_agent.py` Scenario 1:3 家 bidder,2 张 md5 相同 + 3 对 pHash 距离 ≤ 5 → OverallAnalysis 1 行,evidence.md5_matches=2 + phash_matches=3
- [x] 11.6 [L2] Scenario 2:全部小图(<32x32) → skip 哨兵 score=0
- [x] 11.7 [L2] `tests/e2e/test_detect_style_agent.py` Scenario 1:3 家有 technical 文档,mock L-8 Stage1+Stage2 全成功 → OverallAnalysis 1 行,evidence.style_features_per_bidder=3 + global_comparison + limitation_note
- [x] 11.8 [L2] Scenario 2:Stage1 模拟失败 → skip 哨兵,summary 含 "语言风格分析不可用"

## 12. 注册表与 dummy 验证

- [x] 12.1 [L1] `tests/unit/test_detect_registry.py` 新增 `test_no_dummy_run_after_c13`:验证 11 Agent 全部 `evidence_json["algorithm_version"]` 命中真实算法名(非 "dummy" 前缀);既有 dummy 测试断言更新或删除
- [x] 12.2 [L1] 既有 `tests/e2e/test_detect_agents_dummy.py` 中 3 global Agent dummy 测试改为"已替换"测试

## 13. 文档联动

- [x] 13.1 [impl] `backend/README.md` 追加 "C13 detect-agents-global 依赖" 段:Q1~Q5 决策注释 + 3 Agent 算法说明 + 16 env 列表 + algorithm version 三个 + L-5/L-8 mock fixture 入口
- [x] 13.2 [impl] `docs/execution-plan.md` §6 追加 2 行:`2026-04-15 | C13 改名 detect-agents-global(3 global Agent 合并替换)` + `2026-04-15 | C14 改名 detect-llm-judge(judge.py 占位 regex → LLM 综合研判)`(不改 §3 原表)

## 14. L3 手工凭证占位

- [x] 14.1 [manual] 建 `e2e/artifacts/c13-2026-04-15/README.md` 占位:列出 6 张待补截图(启动检测 / error_consistency 铁证 evidence 展开 / error_consistency downgrade 展开 / image_reuse MD5+pHash evidence 展开 / style 三 bidder consistent_groups 展开 / 任一 LLM 失败兜底 banner)+ L1/L2 覆盖证明
- [x] 14.2 [impl] `.gitignore` 加 `c13-*` L3 artifacts 白名单(复用既有 pattern)

## 15. 总汇测试

- [x] 15.1 跑 [L1][L2][L3] 全部测试,全绿(L3 降级手工凭证)
