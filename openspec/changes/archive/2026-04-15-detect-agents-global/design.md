## Context

C6 detect-framework 已注册 11 Agent(C12 扩),其中 8 个 pair/global Agent 的 `run()` 已被 C7~C12 替换为真实算法,仍剩 3 个 global 型 Agent(`error_consistency / style / image_reuse`)的 `run()` 走 dummy(`dummy_global_run`)。本期 C13 一次性替换这 3 个 Agent。

数据层 C5 已就绪:
- `bidder.identity_info` JSONB(L-1 LLM 提取的公司全称/简称/关键人员/资质编号)
- `document_texts.full_text + paragraphs + header_footer`(段落/页眉页脚分离存储)
- `document_images.md5(32 hex) + phash(64 bit, 16 hex)`(C5 用 `imagehash.phash` 生成)

依赖层就绪:`imagehash>=4.3` 已在 `pyproject.toml`,Pillow 已在(C5 image_parser 引)。

C11/C12 已建立的契约可复用:`write_overall_analysis_row` helper(global 型 Agent 写 OverallAnalysis 的统一入口);Agent 级 skip 哨兵(`score=0.0 + participating_subdims=[] + skip_reason`);evidence `enabled / llm_explanation` 占位;algorithm version 字段;严格/宽松两类 env 校验。

## Goals / Non-Goals

**Goals:**

- 替换 3 global Agent 的 dummy run() 为真实算法
- 兑现 spec §F-DA-02 (error_consistency) + §F-DA-03 (image_reuse) + §F-DA-06 (style) + §L-5 + §L-8 全部规格
- error_consistency 的**铁证能力本期就位**(L-5 LLM `direct_evidence=true` → `is_iron_evidence=true`)
- detect 层 LLM 调用点一次到位(L-5 + L-8),让 C14 只专注 judge.py 升级(LLM 综合研判),不背 N+1 个单维度 LLM 兜底
- 11 Agent 注册表契约不动;`registry / engine / judge / context` 全锁定
- 数据层零迁移;依赖层零新增

**Non-Goals:**

- 不做 image_reuse 的 L-7 LLM 非通用图判断(spec "可升铁证"非"必升",占位字段保留,留 follow-up)
- 不做 image_reuse 升铁证逻辑(本期 evidence 占位 `llm_non_generic_judgment: null`)
- 不调 `DIMENSION_WEIGHTS`(贴 C6/C10/C11/C12 占位权重,留 C14 LLM 综合研判时统一调)
- 不做 style >20 bidder 的复杂跨组比较算法(简化:每组 ≤20 不跨组比;5 家典型场景不触发)
- 不做 style 局限性说明的 LLM 自动生成(evidence 字段固定文案)
- 不改 11 Agent 注册表 / preflight 函数 / 文件名 / 注册 key
- 不引第三方 LLM 真调用(全走 `llm_mock.py` 单一入口)

## Decisions

### D1 三子包独立并存(不强行共用 `global_impl/`)

**决策**:`backend/app/services/detect/agents/` 下新增 3 个独立子包:

- `error_impl/`(7 文件):`__init__.py`(含 `write_overall_analysis_row` 引用 / `_shape_subdim` helper) / `config.py`(env + ErrorConsistencyConfig dataclass + 严格校验) / `models.py`(SuspiciousSegment / KeywordHit / LLMJudgment / DetectionResult TypedDict) / `keyword_extractor.py`(从 identity_info 抽关键词 + len≥2 过滤 + 高频降权) / `intersect_searcher.py`(在 document_texts.paragraphs + header_footer 两路并集做关键词匹配 + 候选段落 ≤100 截断) / `llm_judge.py`(L-5 调用 + 解析 + 失败兜底) / `scorer.py`(候选段落数 + 直接证据 → 分数公式)
- `image_impl/`(5 文件):`__init__.py` / `config.py`(`IMAGE_REUSE_PHASH_DISTANCE / MIN_WH / MAX_PAIRS` 等 env) / `models.py`(MD5Match / PHashMatch / DetectionResult) / `hamming_comparator.py`(MD5 INNER JOIN + pHash `imagehash.hex_to_hash().__sub__` 比较) / `scorer.py`
- `style_impl/`(6 文件):`__init__.py` / `config.py`(`STYLE_GROUP_THRESHOLD / SAMPLE_PER_BIDDER / TFIDF_FILTER_RATIO` 等) / `models.py`(StyleFeatureBrief / GlobalComparison / DetectionResult) / `sampler.py`(从 technical 角色文档 TF-IDF 过滤高频通用段落 + 5-10 段抽样) / `llm_client.py`(L-8 两阶段调用 + 失败兜底) / `scorer.py`

**rationale**:3 Agent 数据源完全不同(`identity_info` JSONB / `document_images` 表 / `document_texts` 段落),算法形态完全不同(关键词交叉 / 哈希 / LLM 提特征),共享面仅限 `write_overall_analysis_row` helper(已在 C11 建)+ evidence 字段约定 — 强行合并到 `global_impl/` 子包是过度抽象。

**alternatives considered**:
- (A) 共用 `global_impl/` 子包:被否决 — 算法形态不同,共享空间 < 5%,合并后子包内文件命名混乱(`error_keyword_extractor / image_hamming / style_sampler` 平级摆放无收益)

### D2 `_preflight_helpers.bidder_has_identity_info` 新增

**决策**:`_preflight_helpers.py` 新增 `bidder_has_identity_info(session, bidder_id) → bool`,检查 `bidder.identity_info` 字段非空且 dict 非空。`error_consistency.preflight` 既有 "downgrade" 路径精化为调此 helper 判断每个 bidder。

**rationale**:既有 preflight 在 `agents/error_consistency.py` 直接 `b.identity_info` 真值判断,逻辑简单;但 downgrade 路径需要更细 — "全部 bidder 都缺" vs "部分 bidder 缺"语义不同(全部缺 → downgrade;部分缺 → 这部分 bidder 的关键词来源退化为 name)。新 helper 让 preflight 和 run() 内部都能调,语义统一。

**alternatives considered**:
- (A) 不加 helper,在 `error_consistency.run()` 内部自行检查:被否决 — 重复逻辑,前后端校验对不齐风险
- (B) 加更通用的 `bidder_field_nonempty(b, field_name)`:被否决 — 过度抽象,目前只有 identity_info 一处需要

### D3 env 命名空间分离 + 严格/宽松两类校验

**决策**:3 Agent 各自独立 env 前缀:

- `ERROR_CONSISTENCY_*`:`ENABLED`(默认 true) / `MAX_CANDIDATE_SEGMENTS`(默认 100,关键参数严格校验,> 0 整数,否则 raise) / `MIN_KEYWORD_LEN`(默认 2,严格校验) / `LLM_TIMEOUT_S`(默认 30,宽松,< 0 → warn fallback 30) / `LLM_MAX_RETRIES`(默认 2,宽松)
- `IMAGE_REUSE_*`:`ENABLED` / `PHASH_DISTANCE_THRESHOLD`(默认 5,严格,0~64 整数) / `MIN_WIDTH`(默认 32,严格,> 0) / `MIN_HEIGHT`(默认 32) / `MAX_PAIRS`(默认 10000,宽松)
- `STYLE_*`:`ENABLED` / `GROUP_THRESHOLD`(默认 20,严格,>= 2) / `SAMPLE_PER_BIDDER`(默认 8,严格,5~10 区间;贴 spec L-8) / `TFIDF_FILTER_RATIO`(默认 0.3,宽松,0~1) / `LLM_TIMEOUT_S`(默认 60,Stage1+Stage2 总时长) / `LLM_MAX_RETRIES`(默认 2)

**rationale**:3 Agent 阈值语义完全不同(关键词候选数 / phash 距离 / 抽样段数),共用一个前缀会让运维误改;独立前缀让 ops 一眼看明白哪个 Agent 关哪个 env。严格/宽松两类校验贴 C11/C12 约定:关键参数(直接影响算法判定)抛 ValueError;次要参数(性能/超时)warn fallback 默认值。

### D4 error_consistency 算法

**决策**:

1. **关键词抽取**(`keyword_extractor.py`):
   - 从 bidder.identity_info 抽 `公司全称 / 简称 / 关键人员姓名[] / 资质编号[]`
   - 过滤短词:`len < ERROR_CONSISTENCY_MIN_KEYWORD_LEN`(默认 2)的整词丢弃(避免单字符碰撞,RISK-19)
   - downgrade 模式:identity_info 空 → 退化用 `bidder.name` 作为唯一关键词(贴 spec §F-DA-02 "降级运行")

2. **跨 bidder 交叉搜索**(`intersect_searcher.py`):
   - 对每个 bidder pair (A, B):用 A 的关键词在 B 的 `document_texts.paragraphs` + `header_footer` 全文(`headers + footers` 数组并集)做子串匹配
   - 双向:A→B 关键词命中 + B→A 关键词命中,合并去重
   - 候选段落上限 `MAX_CANDIDATE_SEGMENTS`(默认 100,RISK-19 token 爆炸防护);超限按 hit 词数倒序截断
   - 每条 hit 记录:`{paragraph_text, doc_id, doc_role, position, matched_keywords[], source_bidder_id}`

3. **L-5 LLM 深度判断**(`llm_judge.py`):
   - 输入:候选 segments + 双 bidder 名称 + 头尾(spec §L-5 原文)
   - 调用 `llm_mock.py::call_llm_l5(segments, bidders) -> {is_cross_contamination, evidence[], direct_evidence}`
   - LLM 失败兜底:仅展示程序层关键词命中 evidence,不做铁证判定,标 "AI 研判暂不可用"(RISK-20)

4. **铁证标记**:L-5 返 `direct_evidence=true` → AgentRunResult `is_iron_evidence=True`(C6 契约预留字段);否则 false

5. **分数公式**(`scorer.py`,占位):`min(100, hit_segment_count * 20 + (40 if direct_evidence else 0) + (LLM 置信度 * 20 if is_cross_contamination else 0))`;各项权重通过 env 不暴露(本期固定,留 follow-up 若需要再开)

### D5 image_reuse 算法

**决策**:

1. **过滤小图**:宽 < `MIN_WIDTH` 或 高 < `MIN_HEIGHT` 的图过滤(剔除小 icon / 装饰图);DocumentImage 表查询时 SQL WHERE 直接过滤
2. **MD5 精确双路**(优先):跨 bidder 两两 INNER JOIN `document_images.md5`,完全相同 → `MD5Match{md5, doc_id_a, doc_id_b, position_a, position_b}`,`hit_strength=1.0`(`byte_match`)
3. **pHash 感知双路**(MD5 未命中的图集合):用 `imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)` 计算 Hamming distance;距离 ≤ `PHASH_DISTANCE_THRESHOLD`(默认 5)→ `PHashMatch{phash_a, phash_b, distance, ...}`,`hit_strength = 1 - distance / 64`
4. **去重**:同一图对(byte_match)只在 MD5 路记一次,不重复进 pHash 路
5. **MAX_PAIRS 上限**(默认 10000):跨 bidder 图片对数超限按 `hit_strength` 倒序截断(防止超大图库 OOM)
6. **不引 L-7 LLM**:evidence 占位 `llm_non_generic_judgment: null`(留 C14 或独立 follow-up 回填,届时 `is_iron_evidence` 由 LLM 升)
7. **分数公式**:`min(100, md5_match_count * 30 + sum(phash_hit_strength) * 10)`(占位,实战调参)

### D6 style 算法(L-8 两阶段)

**决策**:

1. **抽样**(`sampler.py`):
   - 每 bidder 仅抽 `technical` 角色文档(`bid_documents.doc_role='technical'`,贴 spec §L-8 "技术方案类")
   - 全文段落集合用 TF-IDF 训练 → 过滤 IDF < `TFIDF_FILTER_RATIO`(默认 0.3,即低 30% 高频通用段落)
   - 剩余段落均匀抽样 `SAMPLE_PER_BIDDER`(默认 8)段,每段长度限制 100~300 字(贴 spec L-8)
2. **Stage1**(`llm_client.call_l8_stage1(bidder_name, sampled_paragraphs) → StyleFeatureBrief`):
   - 每 bidder 1 次 LLM 调用 → 风格特征摘要(用词偏好 / 句式 / 标点 / 段落组织)
3. **Stage2**(`llm_client.call_l8_stage2(briefs[]) → GlobalComparison`):
   - 全部 bidder 摘要一次 LLM 比对 → 风格高度一致 bidder 组合列表 + 典型相似特征描述 + 局限性说明(spec 要求"主动声明")
4. **>20 bidder 切组**(简化):按 `bidder_id` 升序切 `STYLE_GROUP_THRESHOLD=20` 一组;每组独立做 Stage2,组间不交叉比较;evidence 标"已自动分组,跨组比较未做"
5. **降级**:任一阶段 LLM 失败 → Agent skip 哨兵(score=0.0 + participating_subdims=[] + skip_reason="LLM 调用失败,Stage<n>");不退化为程序算法(spec §F-DA-06 明确"程序不参与")
6. **evidence 字段**:`{style_features_per_bidder: {bidder_id: brief}, global_comparison: {...}, limitation_note: "风格一致可能源于同一代写服务,需结合其他维度综合判断", grouping_strategy: "single|grouped"}`
7. **分数公式**:`min(100, len(global_comparison.consistent_groups) * 30 + max(group.consistency_score) * 50)`(占位)

### D7 evidence 字段格式三 Agent 统一

**决策**:三 Agent 的 evidence_json 顶层格式统一:

```json
{
  "enabled": true|false,
  "llm_explanation": null,                  // 占位,留 C14 LLM 综合研判回填
  "skip_reason": null|"...",                // skip 哨兵时填
  "participating_subdims": ["sub_dim_a"],   // 实际跑了哪些子检测
  "algorithm_version": "error_consistency_v1",
  // 各 Agent 语义字段:
  "suspicious_segments": [...] |            // error_consistency
  "md5_matches": [...] |                    // image_reuse
  "style_features_per_bidder": {...}        // style
}
```

**rationale**:贴 C11/C12 已建格式,前端按 `enabled` 优先识别,`llm_explanation` 和 `skip_reason` 占位前端可统一渲染 banner。

### D8 LLM mock 单一入口

**决策**:`backend/tests/fixtures/llm_mock.py` 扩 L-5 + L-8 fixture:

- `MOCK_L5_RESPONSES: dict[str, dict]`(按 segments hash key 索引)+ `mock_call_llm_l5(...)` 函数
- `MOCK_L8_STAGE1_RESPONSES` + `mock_call_l8_stage1(...)`
- `MOCK_L8_STAGE2_RESPONSES` + `mock_call_l8_stage2(...)`
- 三 mock 函数支持 `simulate_failure: bool` 触发兜底路径测试

**rationale**:贴 CLAUDE.md "8 个 LLM 调用点共享" 单一入口约定;mock 维护成本集中。

### D9 算法版本号 + DIMENSION_WEIGHTS 不调

**决策**:

- 三 Agent 的 evidence 写 `algorithm_version: "error_consistency_v1" | "image_reuse_v1" | "style_v1"`
- `judge.py::DIMENSION_WEIGHTS` 不调(贴 C12 调整后:`error_consistency=?, style=?, image_reuse=0.05`,让 C14 LLM 综合研判时按实战数据统一调)

**rationale**:本期任务范围聚焦"替换 dummy",权重调整属于 judge 升级范畴,推 C14 一并做,避免分散决策。

### D10 计划文档 + spec sync

**决策**:

- `docs/execution-plan.md §6` 追加 2 行(不改 §3 原表,贴 §6 "保留历史"约定):
  - `2026-04-15 | C13 改名 detect-agents-global(3 global Agent 合并替换) | execution-plan §3 原 bidder-relation 与实际 Agent 注册表不符(C6 framework 从未注册 bidder_relation Agent)`
  - `2026-04-15 | C14 改名 detect-llm-judge(judge.py 占位 regex → LLM 综合研判) | 原 history_cooccur 同上;C14 真实职责是综合研判收官`
- `openspec/specs/detect-framework/spec.md` sync:MODIFIED "11 Agent 骨架"(dummy 列表清空,加 "C13 替换完毕" Scenario)+ ADDED 8 类 Req(error_consistency 算法 / L-5 契约 / image_reuse 算法 / style 算法 / L-8 契约 / mock fixture / evidence 结构 / env)

## Risks / Trade-offs

- **Risk-1**:L-5 LLM 调用 token 爆炸(候选段落过多)→ Mitigation:`MAX_CANDIDATE_SEGMENTS=100` 严格上限 + 短词过滤(`MIN_KEYWORD_LEN=2`)+ TF-IDF 高频降权(RISK-19 已覆盖)
- **Risk-2**:identity_info 部分 bidder 缺,部分有,downgrade 范围模糊 → Mitigation:全缺 → preflight 返 downgrade;部分缺 → 该 bidder 自身关键词退化为 name,其他 bidder 正常用 identity_info
- **Risk-3**:image_reuse 大图库(>1000 图/项目)Hamming 比较 O(n²) 慢 → Mitigation:`MIN_WIDTH/MIN_HEIGHT=32` 过滤小图 + `MAX_PAIRS=10000` 截断;实战监控耗时再升级 BK-tree
- **Risk-4**:style >20 bidder 简化分组丢失跨组对 → Mitigation:本期场景平均 <10 家,触发概率低;evidence 标 `grouping_strategy=grouped` 提示用户;留 follow-up 完整算法
- **Risk-5**:L-5 LLM 误判铁证(false positive)致直接高风险 → Mitigation:LLM mock 失败路径测试 + spec 已要求 `direct_evidence` 字段独立(用户复核可改判,M4 报告页 US-6.4)
- **Trade-off-1**:不做 image_reuse L-7 LLM → 通用 logo 误命中无法升铁证降级;缓解:evidence 占位 + follow-up
- **Trade-off-2**:style 不做跨组比较 → >20 家场景丢失"跨组对"信号;缓解:简化版可用,完整版留 follow-up
- **Trade-off-3**:DIMENSION_WEIGHTS 不调 → judge 加权可能不准,但占位权重 C6/C10/C11/C12 一直延续,本期不破例
