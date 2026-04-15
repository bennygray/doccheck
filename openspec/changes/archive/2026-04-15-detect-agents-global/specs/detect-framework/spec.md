## MODIFIED Requirements

### Requirement: 10 Agent 骨架文件与 dummy run

后端 MUST 在 `app/services/detect/agents/` 下提供 **11** 个 Agent 骨架文件(原 10 + C12 新增 `price_anomaly.py`),每个文件定义一个 Agent 骨架,通过 `@register_agent` 装饰器注册到 AGENT_REGISTRY。

C13 归档后,**全部 11 个 Agent 的 `run()` 均为真实算法,dummy 列表清空**。已替换 Agent:
- pair 型(C7~C11):`text_similarity` / `section_similarity` / `structure_similarity` / `metadata_author` / `metadata_time` / `metadata_machine` / `price_consistency`
- global 型:`price_anomaly`(C12 新增,直接带真实 run)/ `error_consistency`(C13)/ `image_reuse`(C13)/ `style`(C13)

每个骨架文件 MUST 含:
- `preflight` 函数(按 "Agent preflight 前置条件自检" Requirement 规则)
- `run(ctx: AgentContext) -> AgentRunResult` 函数,调用各自子包(`text_sim_impl / section_sim_impl / structure_sim_impl / metadata_impl / price_impl / anomaly_impl / error_impl / image_impl / style_impl`)的真实算法

`AgentRunResult` 是 namedtuple,字段:`score: float, summary: str, evidence_json: dict = {}, is_iron_evidence: bool = False`。当整 Agent 因数据缺失 run 级 skip 时 `score=0.0` 作为哨兵值,evidence 层通过 `participating_fields=[]`(或 `participating_dimensions=[]` / `participating_subdims=[]`,按 Agent 定义)标记。

**注意**:C13 归档后,dummy 列表为空。后续如有新 Agent 加入(如 C14 LLM 综合研判 judge 升级,如需新 Agent),需独立 change 替换。

#### Scenario: 11 Agent 模块加载后注册表完整

- **WHEN** `from app.services.detect import agents` 触发所有 agents 模块加载
- **THEN** `AGENT_REGISTRY` 含 11 条目;每条 `run` 可调

#### Scenario: text_similarity 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["text_similarity"].run(ctx)` 且段落对存在
- **THEN** `evidence_json["algorithm"] == "tfidf_cosine_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: section_similarity 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["section_similarity"].run(ctx)` 且章节切分成功
- **THEN** `evidence_json["algorithm"] == "tfidf_cosine_chapter_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: structure_similarity 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["structure_similarity"].run(ctx)` 且至少一个维度可提取
- **THEN** `evidence_json["algorithm"] == "structure_sim_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: metadata_author 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["metadata_author"].run(ctx)` 且元数据足够
- **THEN** `evidence_json["algorithm"] == "metadata_author_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: metadata_time 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["metadata_time"].run(ctx)` 且元数据时间字段足够
- **THEN** `evidence_json["algorithm"] == "metadata_time_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: metadata_machine 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["metadata_machine"].run(ctx)` 且元数据机器指纹字段足够
- **THEN** `evidence_json["algorithm"] == "metadata_machine_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: price_consistency 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["price_consistency"].run(ctx)` 且双方 PriceItem 存在
- **THEN** `evidence_json["algorithm"] == "price_consistency_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: price_anomaly 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["price_anomaly"].run(ctx)` 且项目下 ≥ 3 家 bidder 已成功解析报价
- **THEN** `evidence_json["algorithm"] == "price_anomaly_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: error_consistency 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["error_consistency"].run(ctx)` 且至少一对 bidder identity_info 非空
- **THEN** `evidence_json["algorithm_version"] == "error_consistency_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: image_reuse 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["image_reuse"].run(ctx)` 且至少 2 个 bidder 有图片
- **THEN** `evidence_json["algorithm_version"] == "image_reuse_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

#### Scenario: style 已替换为真实实现

- **WHEN** 调 `AGENT_REGISTRY["style"].run(ctx)` 且至少 2 个 bidder 有 technical 角色文档
- **THEN** `evidence_json["algorithm_version"] == "style_v1"`(非 dummy 标记),summary 非 "dummy" 前缀

---

## ADDED Requirements

### Requirement: error_consistency 关键词抽取与跨投标人交叉搜索

`error_consistency` Agent MUST 在 `app/services/detect/agents/error_impl/` 子包提供:

1. **`keyword_extractor.extract_keywords(bidder, downgrade: bool) -> list[str]`**:
   - 正常模式(downgrade=False):从 `bidder.identity_info` 抽 `公司全称 / 简称 / 关键人员姓名[] / 资质编号[]` 4 类字段值,平铺为字符串列表
   - 降级模式(downgrade=True):返 `[bidder.name]` 单元素列表(贴 spec §F-DA-02 "用投标人名称做关键词交叉搜索")
   - 长度过滤:整词 `len < ERROR_CONSISTENCY_MIN_KEYWORD_LEN`(默认 2)的丢弃(避免单字符碰撞,RISK-19 防护)
   - 去重 + NFKC 归一化

2. **`intersect_searcher.search(ctx, pair_a, pair_b) -> list[SuspiciousSegment]`**:
   - 取 A 的关键词在 B 的 `document_texts.paragraphs`(数组)+ `document_texts.header_footer.headers + footers`(数组并集)中做子串匹配
   - 取 B 的关键词在 A 的同样字段做反向匹配
   - 双向命中合并去重,每条 hit 含 `{paragraph_text, doc_id, doc_role, position("body"|"header"|"footer"), matched_keywords[], source_bidder_id}`
   - 候选段落总数上限 `ERROR_CONSISTENCY_MAX_CANDIDATE_SEGMENTS`(默认 100,RISK-19 token 爆炸防护);超限按 `len(matched_keywords)` 倒序截断

3. **`run()` 主流程**:对项目内全部 bidder 两两 (A, B),依次调 `extract_keywords` → `intersect_searcher.search` → `llm_judge.call_l5`,产出 PairComparison 行(global 型 Agent 也可能产 pair 行,贴 spec §F-DA-02 "两两比对")

#### Scenario: 正常模式抽 4 类字段

- **WHEN** bidder.identity_info = `{"company_name": "甲建设", "short_name": "甲", "key_persons": ["张三", "李四"], "credentials": ["AB123"]}`,downgrade=False
- **THEN** `extract_keywords` 返 `["甲建设", "甲", "张三", "李四", "AB123"]` 经过滤后(短词 "甲" 被丢弃 → `["甲建设", "张三", "李四", "AB123"]`)

#### Scenario: 降级模式只用 bidder.name

- **WHEN** bidder.identity_info = None,downgrade=True
- **THEN** `extract_keywords` 返 `[bidder.name]`

#### Scenario: 双向交叉搜索

- **WHEN** A 关键词 ["张三"] 出现在 B.paragraphs[3];B 关键词 ["乙公司"] 出现在 A.header_footer.footers[0]
- **THEN** `intersect_searcher.search` 返 2 条 SuspiciousSegment,分别标 source_bidder=A/B 和 position=body/footer

#### Scenario: 候选段落超 100 截断

- **WHEN** 双向命中产生 250 条 SuspiciousSegment
- **THEN** 按 `len(matched_keywords)` 倒序截断到 100 条;evidence 标 `truncated=true, original_count=250`

---

### Requirement: error_consistency L-5 LLM 调用契约与铁证判定

`error_consistency` MUST 调 L-5 LLM 做交叉污染深度判断:

1. **`llm_judge.call_l5(segments: list[SuspiciousSegment], bidder_a, bidder_b) -> LLMJudgment`**:
   - prompt 输入:双方名称 + 候选段落原文片段(spec §L-5)
   - 期望 LLM 返 JSON:`{"is_cross_contamination": bool, "evidence": [{"type": "公司名混入"|"人员名混入"|"案例共用"|"错别字共用", "snippet": str, "position": str}], "direct_evidence": bool, "confidence": float}`
   - 走 `tests/fixtures/llm_mock.py::call_llm_l5`(测试)/ 实际 LLM provider(生产)
   - 重试 `ERROR_CONSISTENCY_LLM_MAX_RETRIES`(默认 2)次

2. **铁证标记规则**:LLM 返 `direct_evidence=true` AND `is_cross_contamination=true` → AgentRunResult `is_iron_evidence=True`(C6 契约预留字段);否则 `is_iron_evidence=False`

3. **JSON 解析容错**:JSON 格式错误 → 视为 LLM 失败走兜底路径(见"降级与失败兜底" Requirement)

#### Scenario: L-5 返铁证

- **WHEN** L-5 mock 返 `{"is_cross_contamination": true, "direct_evidence": true, ...}`
- **THEN** AgentRunResult.is_iron_evidence = True;PairComparison.is_ironclad = True;evidence.llm_judgment.direct_evidence = True

#### Scenario: L-5 返非铁证但污染

- **WHEN** L-5 mock 返 `{"is_cross_contamination": true, "direct_evidence": false, ...}`
- **THEN** AgentRunResult.is_iron_evidence = False;evidence.llm_judgment 完整保存;score 按公式包含 LLM 加分但不强制铁证

#### Scenario: L-5 返 JSON 格式错误

- **WHEN** L-5 mock 返非合法 JSON 字符串
- **THEN** 重试 2 次后视为 LLM 失败,走兜底路径(下一 Requirement 描述)

---

### Requirement: error_consistency 降级路径与 LLM 失败兜底

`error_consistency` Agent MUST 实现两条独立兜底路径,覆盖 RISK-19 / RISK-20:

1. **preflight downgrade(identity_info 缺失)**:
   - preflight 检查全部 bidder `identity_info` — 全部缺失 → preflight 返 `downgrade`(贴现有 preflight Requirement);ctx.downgrade = True
   - run 内部仍调 `extract_keywords(bidder, downgrade=True)` 用 bidder.name + 仍调 `intersect_searcher.search` + **仍调 L-5 LLM**(贴 spec §F-DA-02 "降级模式不做铁证判定" — 降级是"不做铁证",不是"不调 LLM")
   - 但降级模式 `is_iron_evidence` 强制 = False(不论 L-5 返什么);evidence 标 `downgrade_mode=true`,summary 含 "降级检测"

2. **L-5 LLM 调用失败**(多次重试仍异常 / JSON 解析失败 / 超时):
   - 仅展示程序层关键词命中 evidence;不调用铁证判定;score 公式扣减 LLM 那部分(score = `min(100, hit_segment_count * 20)`,无 LLM 加分)
   - evidence 标 `llm_failed=true, llm_failure_reason=str`;summary 含 "AI 研判暂不可用"
   - 覆盖 RISK-20(L-1 失败致铁证静默跳过 → 降级运行而非跳过)

#### Scenario: identity_info 全缺降级仍调 L-5

- **WHEN** ctx.all_bidders 全部 identity_info=None,preflight 返 downgrade,run 被调用
- **THEN** `extract_keywords` 用 bidder.name;`call_l5` 仍被调用;但 `is_iron_evidence` 强制 False;evidence.downgrade_mode = True

#### Scenario: L-5 LLM 失败仅展示关键词命中

- **WHEN** L-5 mock 模拟超时 + 重试 2 次仍失败
- **THEN** `is_iron_evidence` = False;evidence.llm_failed = True;score = `min(100, hit_count * 20)`;summary 含 "AI 研判暂不可用"

---

### Requirement: error_consistency Agent 级 skip 与 evidence_json 结构

Agent `error_consistency` MUST 在以下三类场景走 Agent 级 skip 哨兵或早返:

- preflight 返 `skip`(`len(ctx.all_bidders) < 2`)→ Agent skip,不调 run
- run 内部检测无任何 bidder 有可抽关键词(降级模式连 bidder.name 也空)→ skip 哨兵 `score=0.0`, `participating_subdims=[]`, `skip_reason="no_extractable_keywords"`
- env `ERROR_CONSISTENCY_ENABLED=false` → 早返不执行 run,evidence.enabled=false

evidence_json 顶层结构(每对 PairComparison.evidence_json):

```json
{
  "enabled": true,
  "algorithm_version": "error_consistency_v1",
  "downgrade_mode": false,
  "llm_failed": false,
  "llm_failure_reason": null,
  "suspicious_segments": [
    {"paragraph_text": "...", "doc_id": 12, "doc_role": "technical", "position": "body",
     "matched_keywords": ["张三", "AB123"], "source_bidder_id": 5}
  ],
  "truncated": false,
  "original_count": 23,
  "llm_judgment": {
    "is_cross_contamination": true,
    "direct_evidence": true,
    "evidence": [...],
    "confidence": 0.85
  } | null,
  "llm_explanation": null,
  "skip_reason": null,
  "participating_subdims": ["keyword_intersect", "llm_l5"]
}
```

#### Scenario: ENABLED=false 早返

- **WHEN** `ERROR_CONSISTENCY_ENABLED=false`
- **THEN** Agent 早返;evidence.enabled = false;不调 extractor / searcher / llm

#### Scenario: 无可抽关键词 skip 哨兵

- **WHEN** 全部 bidder identity_info=None 且 bidder.name=""(极端场景)
- **THEN** AgentRunResult.score = 0.0;evidence.participating_subdims = [];evidence.skip_reason = "no_extractable_keywords"

---

### Requirement: error_consistency 环境变量

`error_consistency` MUST 暴露 5 个 env(关键参数严格校验,次要参数 warn fallback):

| env | 默认 | 类型 | 校验 |
|---|---|---|---|
| `ERROR_CONSISTENCY_ENABLED` | true | bool | 任意 |
| `ERROR_CONSISTENCY_MAX_CANDIDATE_SEGMENTS` | 100 | int > 0 | 严格,违反 raise ValueError |
| `ERROR_CONSISTENCY_MIN_KEYWORD_LEN` | 2 | int > 0 | 严格 |
| `ERROR_CONSISTENCY_LLM_TIMEOUT_S` | 30 | int > 0 | 宽松,< 0 → warn fallback 30 |
| `ERROR_CONSISTENCY_LLM_MAX_RETRIES` | 2 | int >= 0 | 宽松 |

#### Scenario: 关键 env 非法 raise

- **WHEN** `ERROR_CONSISTENCY_MAX_CANDIDATE_SEGMENTS=-5`
- **THEN** `ErrorConsistencyConfig.from_env()` 抛 ValueError

#### Scenario: 次要 env 非法 warn fallback

- **WHEN** `ERROR_CONSISTENCY_LLM_TIMEOUT_S=-10`
- **THEN** logger.warning 记录;config.llm_timeout_s = 30(默认)

---

### Requirement: image_reuse MD5 + pHash 双路算法

`image_reuse` Agent MUST 在 `app/services/detect/agents/image_impl/` 子包提供:

1. **小图过滤**:SQL 查询 `document_images` 时直接 WHERE `width >= IMAGE_REUSE_MIN_WIDTH AND height >= IMAGE_REUSE_MIN_HEIGHT`(默认 32),剔除小 icon / 装饰图

2. **MD5 精确双路**(优先):跨 bidder 两两 INNER JOIN `document_images.md5`,完全相同 → `MD5Match{md5, doc_id_a, doc_id_b, position_a, position_b, bidder_a_id, bidder_b_id}`,`hit_strength=1.0`,`match_type="byte_match"`

3. **pHash 感知双路**(在 MD5 未命中的图集合上):用 `imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)` 计算 Hamming distance;距离 ≤ `IMAGE_REUSE_PHASH_DISTANCE`(默认 5)→ `PHashMatch{phash_a, phash_b, distance, ...}`,`hit_strength = 1 - distance / 64`,`match_type="visual_similar"`

4. **去重**:同一 (doc_a, doc_b) 图对在 MD5 路命中后,不再进 pHash 路(避免重复)

5. **MAX_PAIRS 上限**(默认 10000):跨 bidder 图片对数超限按 `hit_strength` 倒序截断;evidence 标 `truncated=true`

6. **不引 L-7 LLM 非通用图判断**:本期 evidence 占位 `llm_non_generic_judgment: null`(留 follow-up 回填,届时 `is_iron_evidence` 由 L-7 判定升)

7. **分数公式**(占位):`min(100, md5_match_count * 30 + sum(phash_hit_strength) * 10)`

#### Scenario: MD5 命中字节匹配

- **WHEN** A.images 与 B.images 有 1 张 md5 相同
- **THEN** evidence.md5_matches 含 1 条 `{md5, hit_strength=1.0, match_type="byte_match"}`;score >= 30

#### Scenario: pHash 命中视觉相似

- **WHEN** A.images 与 B.images 无 md5 相同,但有 1 对 phash Hamming distance = 3
- **THEN** evidence.phash_matches 含 1 条 `{distance=3, hit_strength≈0.953, match_type="visual_similar"}`

#### Scenario: 小图被过滤

- **WHEN** A 与 B 各有 1 张 16x16 的 icon md5 相同
- **THEN** SQL 直接过滤,evidence.md5_matches = []

#### Scenario: MAX_PAIRS 截断

- **WHEN** 跨 bidder 图片对计算出 25000 对命中
- **THEN** 按 hit_strength 倒序截断到 10000;evidence.truncated=true, original_count=25000

#### Scenario: image_reuse 不升铁证

- **WHEN** 任意 MD5/pHash 命中
- **THEN** AgentRunResult.is_iron_evidence = False(本期不做 L-7);evidence.llm_non_generic_judgment = null

---

### Requirement: image_reuse Agent 级 skip 与 evidence_json 结构

Agent `image_reuse` MUST 在以下场景走 Agent 级 skip 哨兵或早返:

- preflight 返 `skip`(< 2 bidder 有图片)→ Agent skip
- env `IMAGE_REUSE_ENABLED=false` → 早返,evidence.enabled=false
- run 内部小图过滤后实际可比对图集合不足(单 bidder 仅 0 张大图)→ skip 哨兵 `score=0.0, participating_subdims=[], skip_reason="no_comparable_images_after_size_filter"`

evidence_json 顶层结构(写入 OverallAnalysis,global 型):

```json
{
  "enabled": true,
  "algorithm_version": "image_reuse_v1",
  "md5_matches": [
    {"md5": "abc...", "doc_id_a": 12, "doc_id_b": 34,
     "bidder_a_id": 5, "bidder_b_id": 7, "position_a": "body", "position_b": "body",
     "hit_strength": 1.0, "match_type": "byte_match"}
  ],
  "phash_matches": [
    {"phash_a": "ff00...", "phash_b": "ff01...", "distance": 3, "hit_strength": 0.953,
     "doc_id_a": 12, "doc_id_b": 34, "bidder_a_id": 5, "bidder_b_id": 7,
     "match_type": "visual_similar"}
  ],
  "truncated": false,
  "original_count": 5,
  "llm_non_generic_judgment": null,
  "llm_explanation": null,
  "skip_reason": null,
  "participating_subdims": ["md5_exact", "phash_hamming"]
}
```

#### Scenario: ENABLED=false 早返

- **WHEN** `IMAGE_REUSE_ENABLED=false`
- **THEN** Agent 早返,evidence.enabled = false

#### Scenario: 全部小图被过滤后 skip 哨兵

- **WHEN** 全部 bidder 仅有 16x16 装饰小图,过滤后 0 张可比对
- **THEN** AgentRunResult.score=0.0,evidence.skip_reason="no_comparable_images_after_size_filter"

---

### Requirement: image_reuse 环境变量

`image_reuse` MUST 暴露以下 env(关键参数严格校验,次要参数 warn fallback):

| env | 默认 | 类型 | 校验 |
|---|---|---|---|
| `IMAGE_REUSE_ENABLED` | true | bool | 任意 |
| `IMAGE_REUSE_PHASH_DISTANCE_THRESHOLD` | 5 | int 0~64 | 严格,违反 raise |
| `IMAGE_REUSE_MIN_WIDTH` | 32 | int > 0 | 严格 |
| `IMAGE_REUSE_MIN_HEIGHT` | 32 | int > 0 | 严格 |
| `IMAGE_REUSE_MAX_PAIRS` | 10000 | int > 0 | 宽松,< 1 → warn fallback 10000 |

#### Scenario: 关键 env 非法 raise

- **WHEN** `IMAGE_REUSE_PHASH_DISTANCE_THRESHOLD=128`
- **THEN** `ImageReuseConfig.from_env()` 抛 ValueError(超 0~64 范围)

---

### Requirement: style L-8 两阶段 LLM 算法

`style` Agent MUST 在 `app/services/detect/agents/style_impl/` 子包提供:

1. **`sampler.sample(ctx, bidder) -> list[str]`**:
   - 仅取 bidder 的 `technical` 角色文档(`bid_documents.doc_role='technical'`,贴 spec §L-8 "技术方案类")
   - 全文段落集合做 TF-IDF 训练(`TfidfVectorizer`)→ 计算每段平均 IDF 权重 → 过滤掉 IDF 低于 `STYLE_TFIDF_FILTER_RATIO`(默认 0.3,即低 30% 高频通用段落,贴 spec §L-8 "TF-IDF 过滤掉高频通用段落如法规条文")
   - 剩余段落均匀抽样 `STYLE_SAMPLE_PER_BIDDER`(默认 8)段;每段过长截断到 300 字、过短(< 100 字)丢弃,贴 spec L-8 "5-10 段,每段 100-300 字"
   - 抽样不足 `min_sample`(默认 3 段)的 bidder 标 `insufficient_sample=true`

2. **`llm_client.call_l8_stage1(bidder_name, sampled_paragraphs) -> StyleFeatureBrief`**:
   - 每 bidder 1 次 LLM 调用,返 `{"用词偏好": str, "句式特点": str, "标点习惯": str, "段落组织": str}`
   - 走 `tests/fixtures/llm_mock.py::call_l8_stage1`

3. **`llm_client.call_l8_stage2(briefs: list[StyleFeatureBrief]) -> GlobalComparison`**:
   - 全部 bidder 摘要一次 LLM 比对,返 `{"consistent_groups": [{"bidder_ids": [1,2], "consistency_score": 0.85, "typical_features": str}], "limitation_note": str}`
   - 走 `tests/fixtures/llm_mock.py::call_l8_stage2`

4. **分数公式**(占位):`min(100, len(consistent_groups) * 30 + max(group.consistency_score * 100 for group in consistent_groups, default=0) * 0.5)`

5. **局限性说明**(spec §F-DA-06 强制要求):evidence.limitation_note 固定写入 `"风格一致可能源于同一主体操控,也可能源于委托同一代写服务,需结合其他维度综合判断"`

#### Scenario: Stage1 + Stage2 全成功

- **WHEN** 3 bidder 各有 ≥ 8 段技术段落,L-8 mock Stage1 返 3 brief,Stage2 返 1 consistent_group [bidder_1, bidder_2]
- **THEN** evidence.style_features_per_bidder = 3 brief;evidence.global_comparison.consistent_groups 含 1 group;evidence.limitation_note 已填

#### Scenario: 抽样后高频段落被过滤

- **WHEN** bidder 100 段中 70 段为通用法规条文(IDF 低)
- **THEN** sampler 过滤后剩 30 段,从中抽 8 段送 Stage1

#### Scenario: 单 bidder 抽样不足

- **WHEN** bidder.technical 文档仅有 2 段 100~300 字段落
- **THEN** sampler 标 `insufficient_sample=true`;Stage1 仍调用但 brief 标 `low_confidence`(简化:本期不强制 skip 该 bidder,evidence 标记)

---

### Requirement: style >20 bidder 自动分组

`style` Agent MUST 在 `len(ctx.all_bidders) > STYLE_GROUP_THRESHOLD`(默认 20)时按以下规则自动分组(贴 spec §F-DA-06 ">20 投标人时自动分组以避免超出 context 窗口"):

- 按 `bidder_id` 升序切片为 `ceil(N/20)` 组,每组 ≤ 20 个 bidder
- 每组独立做 Stage1(仍每 bidder 1 次调用)+ Stage2(每组 1 次调用)
- **不跨组比较**(简化版,贴 design.md D6 "完整跨组算法留 follow-up")
- evidence.grouping_strategy = `"grouped"`(< 20 时为 `"single"`);evidence.group_count = `ceil(N/20)`
- 5 家典型场景不触发分组路径(grouping_strategy="single")

#### Scenario: 25 bidder 切 2 组

- **WHEN** ctx.all_bidders 含 25 个 bidder,STYLE_GROUP_THRESHOLD=20
- **THEN** 第 1 组 bidder_id 升序前 20 个,第 2 组后 5 个;Stage1 调 25 次,Stage2 调 2 次;evidence.grouping_strategy="grouped", group_count=2

#### Scenario: 5 bidder 不分组

- **WHEN** ctx.all_bidders 含 5 个 bidder
- **THEN** 直接 Stage1 5 次 + Stage2 1 次;evidence.grouping_strategy="single"

---

### Requirement: style Agent 级 skip 与 evidence_json 结构

Agent `style` MUST 在以下场景走 Agent 级 skip 哨兵或早返(贴 spec §F-DA-06 "任一阶段 LLM 失败则整个维度跳过"):

- preflight 返 `skip`(< 2 bidder 有 technical 文档)→ Agent skip
- env `STYLE_ENABLED=false` → 早返,evidence.enabled=false
- Stage1 任一 bidder LLM 调用失败(重试后仍失败)→ Agent skip 哨兵 `score=0.0, participating_subdims=[], skip_reason="L-8 Stage1 LLM 调用失败"`
- Stage2 LLM 调用失败 → Agent skip 哨兵 `score=0.0, participating_subdims=[], skip_reason="L-8 Stage2 LLM 调用失败"`

evidence_json 顶层结构(写入 OverallAnalysis):

```json
{
  "enabled": true,
  "algorithm_version": "style_v1",
  "grouping_strategy": "single",
  "group_count": 1,
  "style_features_per_bidder": {
    "5": {"用词偏好": "...", "句式特点": "...", "标点习惯": "...", "段落组织": "...", "low_confidence": false}
  },
  "global_comparison": {
    "consistent_groups": [
      {"bidder_ids": [5, 7], "consistency_score": 0.85, "typical_features": "..."}
    ]
  },
  "limitation_note": "风格一致可能源于同一主体操控,也可能源于委托同一代写服务,需结合其他维度综合判断",
  "llm_explanation": null,
  "skip_reason": null,
  "participating_subdims": ["llm_l8_stage1", "llm_l8_stage2"]
}
```

#### Scenario: ENABLED=false 早返

- **WHEN** `STYLE_ENABLED=false`
- **THEN** Agent 早返,evidence.enabled = false,不调 sampler / llm_client

#### Scenario: Stage1 失败整 Agent skip

- **WHEN** 3 bidder 中 1 bidder 的 Stage1 LLM 调用重试 2 次仍失败
- **THEN** AgentRunResult.score=0.0,evidence.skip_reason="L-8 Stage1 LLM 调用失败",summary 含 "语言风格分析不可用"

#### Scenario: Stage2 失败整 Agent skip

- **WHEN** Stage1 全部 3 bidder 成功,Stage2 LLM 调用重试 2 次仍失败
- **THEN** AgentRunResult.score=0.0,evidence.skip_reason="L-8 Stage2 LLM 调用失败"

---

### Requirement: style 环境变量

`style` MUST 暴露以下 env(关键参数严格校验,次要参数 warn fallback):

| env | 默认 | 类型 | 校验 |
|---|---|---|---|
| `STYLE_ENABLED` | true | bool | 任意 |
| `STYLE_GROUP_THRESHOLD` | 20 | int >= 2 | 严格,违反 raise |
| `STYLE_SAMPLE_PER_BIDDER` | 8 | int 5~10 | 严格(贴 spec L-8 5-10 段) |
| `STYLE_TFIDF_FILTER_RATIO` | 0.3 | float 0~1 | 宽松,越界 → warn fallback 0.3 |
| `STYLE_LLM_TIMEOUT_S` | 60 | int > 0 | 宽松 |
| `STYLE_LLM_MAX_RETRIES` | 2 | int >= 0 | 宽松 |

#### Scenario: 关键 env 非法 raise

- **WHEN** `STYLE_SAMPLE_PER_BIDDER=20`
- **THEN** `StyleConfig.from_env()` 抛 ValueError(超 5~10 范围)

#### Scenario: 次要 env 越界 warn fallback

- **WHEN** `STYLE_TFIDF_FILTER_RATIO=2.5`
- **THEN** logger.warning 记录;config.tfidf_filter_ratio = 0.3

---

### Requirement: _preflight_helpers.bidder_has_identity_info 新增

`backend/app/services/detect/agents/_preflight_helpers.py` MUST 新增:

```python
def bidder_has_identity_info(bidder) -> bool:
    """检查 bidder.identity_info 字段非空且 dict 非空。"""
    info = bidder.identity_info
    if info is None:
        return False
    if not isinstance(info, dict):
        return False
    return bool(info)  # 空 dict 返 False
```

`error_consistency.preflight` MUST 调此 helper 判断每个 bidder 的 identity_info 状态:全部缺 → downgrade;部分缺 → ok(downgrade 在 run 内部按 bidder 分别决策);全部有 → ok。

#### Scenario: identity_info 字段为空 dict 返 False

- **WHEN** bidder.identity_info = `{}`
- **THEN** `bidder_has_identity_info(bidder)` 返 False

#### Scenario: identity_info 字段为 None 返 False

- **WHEN** bidder.identity_info = None
- **THEN** `bidder_has_identity_info(bidder)` 返 False

#### Scenario: identity_info 含值返 True

- **WHEN** bidder.identity_info = `{"company_name": "甲建设"}`
- **THEN** `bidder_has_identity_info(bidder)` 返 True

---

### Requirement: llm_mock.py 扩展 L-5 + L-8 两阶段 fixture

`backend/tests/fixtures/llm_mock.py` MUST 扩展支持 L-5(error_consistency)+ L-8 两阶段(style):

1. **L-5 mock**:
   - `MOCK_L5_RESPONSES: dict[str, dict]` — key 由 `(bidder_a_id, bidder_b_id, segments_hash)` 派生;value 为 LLMJudgment dict
   - `mock_call_llm_l5(segments, bidder_a, bidder_b, *, simulate_failure: bool = False) -> LLMJudgment`
   - `simulate_failure=True` 抛 `LLMCallError("simulated failure")` 触发兜底测试

2. **L-8 Stage1 mock**:
   - `MOCK_L8_STAGE1_RESPONSES: dict[int, StyleFeatureBrief]` — key 为 bidder_id
   - `mock_call_l8_stage1(bidder_id, sampled_paragraphs, *, simulate_failure: bool = False) -> StyleFeatureBrief`

3. **L-8 Stage2 mock**:
   - `MOCK_L8_STAGE2_RESPONSES: dict[str, GlobalComparison]` — key 由 sorted bidder_id tuple 派生
   - `mock_call_l8_stage2(briefs, *, simulate_failure: bool = False) -> GlobalComparison`

4. **monkeypatch 注入约定**:测试通过 `monkeypatch.setattr(llm_judge, "call_l5", mock_call_llm_l5)` 等方式替换实际调用;production 走真实 LLM provider

5. **fixture 文件保持单一入口**:贴 CLAUDE.md "8 个 LLM 调用点共享" 约定;不在 production 代码中分散 mock 逻辑

#### Scenario: L-5 mock 返铁证响应

- **WHEN** 测试 setup MOCK_L5_RESPONSES 含特定 key;test 调 `mock_call_llm_l5(segments, ...)` 传匹配输入
- **THEN** 返预设的 `{"is_cross_contamination": true, "direct_evidence": true, ...}` LLMJudgment

#### Scenario: simulate_failure 触发兜底测试

- **WHEN** 测试调 `mock_call_l8_stage2(briefs, simulate_failure=True)`
- **THEN** 抛 `LLMCallError`;Agent 走 skip 哨兵路径

#### Scenario: 三 LLM 入口接口签名独立

- **WHEN** 测试代码同时 monkeypatch L-5 / L-8 stage1 / L-8 stage2
- **THEN** 三 mock 互不干扰;不同 Agent 的 LLM 测试隔离
