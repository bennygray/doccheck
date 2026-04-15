# 项目 Handoff

> **跨会话/跨人接手的现场视角快照。** 计划视角见 `docs/execution-plan.md` §5。
>
> 本文档职责:记录"现在人在哪、下一步干什么、有什么没说清"。
> 最近变更历史只保留 5 条,更早历史去 `git log` 查。

---

## 1. 当前状态快照

| 项 | 值 |
|---|---|
| 当前里程碑 | **M3 进行中(8/9)**,C13 `detect-agents-global` 已 archive,待 commit |
| 当前 change | C13 已 archive,即将随本次 commit 一起提交 |
| 当前任务行 | N/A |
| 最新 commit | C12 归档 `f04eb30` — C13 archive commit 即将产生 |
| 工作区 | C13 全量改动:**检测层(C13 主体)**:**新增 3 子包共 18 文件**(`error_impl/` 7:`__init__.py` 复用 anomaly_impl write_overall_analysis_row / `config.py` 5 env / `models.py` 5 TypedDict(KeywordHit / SuspiciousSegment / LLMJudgment / PairResult / DetectionResult)/ `keyword_extractor.py` 4 类字段平铺+短词过滤+NFKC 归一+去重+downgrade 退化 bidder.name / `intersect_searcher.py` 双向跨 bidder 子串匹配+MAX_CANDIDATE_SEGMENTS 截断按 matched_keywords 倒序 / `llm_judge.py` L-5 调用+系统 prompt+JSON 解析容错+重试 / `scorer.py` pair 级+Agent 级 max 公式;`image_impl/` 5:`__init__.py` / `config.py` 5 env(PHASH 严格 0~64)/ `models.py` 3 TypedDict(MD5Match/PHashMatch/DetectionResult)/ `hamming_comparator.py` SQL 过滤小图+MD5 INNER JOIN+pHash `imagehash.hex_to_hash().__sub__`+同对图去重+MAX_PAIRS 截断 / `scorer.py`;`style_impl/` 6:`__init__.py` / `config.py` 6 env(SAMPLE 严格 5~10)/ `models.py` 4 TypedDict(StyleFeatureBrief/ConsistentGroup/GlobalComparison/DetectionResult)/ `sampler.py` technical 角色+TfidfVectorizer IDF 过滤+长度过滤 100~300+均匀抽样 / `llm_client.py` L-8 Stage1+Stage2+共享 `_call_with_retry_and_parse`(解析失败消费重试名额) / `scorer.py`+LIMITATION_NOTE 固定文案)+ **重写 3 Agent run()**(`error_consistency.py` 5 层兜底:ENABLED=false 早返 / preflight 任一缺 downgrade 标记仍调 L-5 / 无可抽关键词 skip 哨兵 / L-5 失败仅展示程序 evidence 不铁证 / L-5 direct_evidence=true → has_iron_evidence=True;遍历 C(n,2) pair 产 pair_results 列表;写 1 行 OA;`image_reuse.py` 3 层兜底:disabled 早返 / 小图过滤后 0 张 skip 哨兵 / 正常双路;`style.py` 4 层兜底:disabled / preflight skip / Stage1 失败 / Stage2 失败;>20 bidder 按 `STYLE_GROUP_THRESHOLD=20` 自动分组每组独立跑 Stage1+Stage2,组间不跨比)+ **`_preflight_helpers.bidder_has_identity_info`** 新增(同步纯属性判断,None/非 dict/空 dict 全返 False)+ **判别层**:`judge.py::compute_report` +3 行支持 global 型 Agent 铁证升级(读 `OverallAnalysis.evidence_json["has_iron_evidence"]`)+ **LLM mock 扩展**:`tests/fixtures/llm_mock.py` 扩 L-5 + L-8 两阶段 9 builder/fixture(`make_l5_response` / `mock_llm_l5_iron/non_iron/no_contamination/failed/bad_json` / `make_l8_stage1_response` / `make_l8_stage2_response` / `mock_llm_l8_full_success/stage1_failed/stage2_failed/bad_json_stage1`)+ **agents/__init__.py** 文件头注释清 dummy(dummy 列表已空)+ **L1 16 test 文件 131 新用例**(error 7:config 10 / keyword_extractor 10 / intersect_searcher 8 / llm_judge 9 / scorer 7 / preflight 8 / run 7;image 4:config 8 / hamming_comparator 10 / scorer 5 / run 6;style 5:config 10 / sampler 9 / llm_client 8 / scorer 6 / run 9)+ **L2 3 test 文件 8 Scenario**(error 4 / image 2 / style 2)+ **`test_detect_registry.py` 新增 `test_no_dummy_run_after_c13`**(inspect 三 global Agent run 模块路径无 _dummy)+ **既有测试调整 3 处**(`test_detect_judge.py` judge.py 改动后 `getattr(oa, "evidence_json", None) or {}` 兼容既有 SimpleNamespace mock;`test_run_detection_agent_timeout` monkeypatch error_consistency 为 0.5s sleep 慢 run 触发 timeout 路径,贴真实 Agent 不再 sleep 事实;`test_dummy_global_run_writes_overall_analysis` 保留 — style.run 在 `< 2 bidder` 补写 OA 让前端可见 skip_reason)+ **doc_texts 行级 SQL**:apply 现场修正 — spec 写 paragraphs/header_footer JSONB 数组,实际 DocumentText 是行级表(location 字段),intersect_searcher 用 SQL 行级查询(language 等价)+ **`imagehash.__sub__` → int(...)** cast(numpy int64 JSONB 序列化失败兜底)+ `backend/README.md` 新增"C13 detect-agents-global 依赖"完整段(Q1~Q5 决策 / apply 现场决策 / 3 Agent 算法 / 16 env / LLM mock 入口 / algorithm version 3 个)+ `.gitignore` 加 `c13-*` 白名单 + `e2e/artifacts/c13-2026-04-15/README.md` L3 手工凭证占位(6 张待补截图 + L1/L2 覆盖证明)+ `openspec/specs/detect-framework/spec.md` sync(+14 ADDED + 1 MODIFIED Req,50 → 64 Req;**sync 后修正 5 处**:AgentRunResult 仍 3 字段不扩,铁证契约改为 global 走 evidence 顶层 has_iron_evidence,pair 走 PairComparison.is_ironclad)+ `docs/execution-plan.md §6` 追加 2 行(C13 改名 detect-agents-global / C14 改名 detect-llm-judge,保留 §3 原表)。**测试合计 883 全绿**(C12 基线 743 → C13 883,净增 140 用例:L1 131 + L2 8 + 注册表 1) |

---

## 2. 本次 session 关键决策(2026-04-15,C13 propose+apply+archive)

### propose 阶段已敲定(5 决策)

- **Q1 合并 1 个 change `detect-agents-global`**(用户拍板):3 global Agent(error_consistency / style / image_reuse)共一个 change;3 子包并存不强行共用(耦合弱,共享仅限 write_overall_analysis_row helper)
- **Q2 (A) error_consistency 程序 + L-5 LLM 全落**(用户拍板):铁证本期兑现;贴 spec §F-DA-02 + §L-5 明文"铁证级 + LLM 专属 prompt",不推 C14;拒绝 B(推后让 C14 scope 失控)/ C(介于两档无价值)
- **Q3 (C) image_reuse MD5 + pHash 双路**(用户拍板):MD5 字节级独占 + pHash 视觉相似;不引 L-7 非通用图 LLM(spec "可升"非"必升",evidence 占位 llm_non_generic_judgment=null 留 follow-up);拒绝 A 纯 MD5(几乎不碰撞)/ B 纯 pHash(丢字节级强信号)/ D 全引 LLM(scope 失控)
- **Q4 (C) style L-8 两阶段全 LLM**(用户拍板):贴 spec §F-DA-06 明文"LLM 独有,程序不参与";TF-IDF 先过滤高频通用段;>20 bidder 自动分组每组 ≤20;拒绝 A 纯程序(spec 违背)/ B 双轨(TF-IDF 预筛行业共性噪声严重失真)
- **Q5 依赖**:无新增(`imagehash>=4.3` 已在 C5 image_parser 引入),Q5 自动消化

### propose 阶段我自己定(实施细节,写入 design D1~D15)

- **D1 三子包独立并存**:error_impl 7 / image_impl 5 / style_impl 6 文件;3 Agent 数据源/算法耦合弱,拒绝共用 global_impl/(过度抽象)
- **D2 `bidder_has_identity_info` helper 新增**(同步纯属性判断,None/非 dict/空 dict 全返 False)
- **D3 env 三命名空间分离**:ERROR_CONSISTENCY_* 5 / IMAGE_REUSE_* 5 / STYLE_* 6(共 16 env);严格/宽松两类校验贴 C11/C12
- **D4 error_consistency 算法**:4 类字段 keyword 平铺+短词 len≥2 过滤+NFKC 归一+去重 → 双向跨 bidder 子串匹配+MAX_CANDIDATE_SEGMENTS=100 截断 → L-5 LLM 铁证判定;RISK-19/20 覆盖
- **D5 image_reuse 算法**:SQL 层 MIN_W/H 过滤小图 → MD5 独占 + pHash `imagehash.hex_to_hash().__sub__` Hamming distance ≤ 5 → MAX_PAIRS=10000 倒序截断
- **D6 style L-8 两阶段**:sampler 仅 technical 角色+TF-IDF 过滤 IDF 低 30%+长度 100~300+均匀抽 8 段 → Stage1 每 bidder 1 次 → Stage2 全局 1 次;>20 bidder 切 ≤20 分组不跨比(完整算法 follow-up)
- **D7 降级两层**:preflight downgrade(任一 bidder 缺 identity_info)run 仍调 L-5 但 is_iron_evidence 强制 False / L-5 LLM 失败仅展示关键词 evidence 不铁证
- **D8 铁证契约**:设计是 AgentRunResult 扩 is_iron_evidence 字段(apply 期改走 OA.evidence_json.has_iron_evidence)
- **D9 image_reuse 不升铁证**:spec "可升"非"必升",evidence 占位 llm_non_generic_judgment=null follow-up
- **D10 style 局限性说明**:固定文案"风格一致可能源于同一代写服务,需结合其他维度综合判断"(spec §F-DA-06 强制)
- **D11 evidence 三 Agent 字段格式统一**:`enabled / algorithm_version / llm_explanation / skip_reason / participating_subdims` + 各自语义字段
- **D12 LLM mock 单一入口**:llm_mock.py 扩 L-5 + L-8 两阶段 9 fixture
- **D13 algorithm version**:error_consistency_v1 / image_reuse_v1 / style_v1
- **D14 DIMENSION_WEIGHTS 不调**:本期聚焦替换 dummy,权重调整留 C14 LLM 综合研判
- **D15 计划文档**:execution-plan §6 追加 2 行(C13 改名 + C14 改名),不改 §3 原表

### apply 阶段就地敲定(重要现场决策)

- **不扩 `AgentRunResult` NamedTuple**(原 spec/design D8 写偏):实际 C6 未预留 is_iron_evidence 字段;改走 global 型 Agent 把 has_iron_evidence 写 OverallAnalysis.evidence_json 顶层,`judge.py::compute_report` +3 行扩展读该字段升铁证(pair 型不变,仍 PairComparison.is_ironclad)
- **`error_consistency.preflight` 保留"任一缺 → downgrade"语义**(贴 spec 原文 + 既有 preflight test);part 试过"全缺才 downgrade"但会破 pre-existing test,回贴保守方案
- **`document_texts` 实际是行级表**(location 字段 body/header/footer/textbox/table_row),非 spec 写的 JSONB 数组;intersect_searcher 改 SQL 行级查询,语义等价(spec 文本需在下次 cleanup 修正,但不影响 C13 功能)
- **`imagehash.__sub__` 返 numpy int64**:需显式 `int(...)` cast,否则 JSONB 序列化失败 `TypeError: Object of type int64 is not JSON serializable`
- **`call_with_retry_and_parse` 合并重试+解析**:JSON 解析失败也消费重试名额(贴 L-5 llm_judge 行为一致);否则 style test `test_stage1_retry_succeeds` 失败(首次"bad json" parser fail 后应该重试,而非直接返 None)
- **3 个既有测试需改动**:
  - `test_detect_judge.py` 用 SimpleNamespace mock → 加 `getattr(oa, "evidence_json", None) or {}` 保护读
  - `test_run_detection_agent_timeout` 原依赖 dummy Agent sleep 0.2-1s;C13 后 dummy 清空 → monkeypatch error_consistency 为 0.5s sleep 慢 run 触发 timeout 路径
  - `test_dummy_global_run_writes_overall_analysis` 用 empty all_bidders → style.run < 2 bidder 从 skip 改为仍写 OA(贴 enabled=false 早返写 OA 语义一致)
- **`error_impl/llm_judge.py` 内嵌 Chinese 引号 bug**:一处 `"真正的交叉污染"` ASCII 双引号终结外层 string → SyntaxError;改用 `「真正的交叉污染」` Chinese 书名号
- **L3 e2e seed fixture 需要**:BidDocument 必填 `md5`(NOT NULL)+ `source_archive`(NOT NULL);测试 seed 必须显式设
- **spec sync 后手动修正 5 处**:AgentRunResult 去 is_iron_evidence(贴 apply 实际不扩 NamedTuple),铁证契约 pair/global 两路改述

### 文档联动

- **`backend/README.md`** 新增 "C13 detect-agents-global 依赖" 完整段:Q1~Q5 决策 + apply 现场决策 + 3 Agent 算法摘要 + 16 env + LLM mock 入口约定 + 3 algorithm version
- **`openspec/specs/detect-framework/spec.md`** sync:MODIFIED 1 Req("11 Agent 骨架 dummy run")+ ADDED 14 Req(error 5 / image 3 / style 4 / helper 1 / mock 1),total 50 → 64 Req;sync 后手动修正 5 处 is_iron_evidence 契约
- **`docs/execution-plan.md §6`** 追加 2 行:C13 改名 detect-agents-global + C14 改名 detect-llm-judge(§3 原表保留历史)
- **`.gitignore`** 加 `c13-*` L3 artifacts 白名单
- **`e2e/artifacts/c13-2026-04-15/README.md`** L3 手工凭证占位(6 张待补截图 + L1/L2 覆盖证明)
- **`docs/handoff.md`** 即本次更新

---

## 2.bak_C12 上一 session 关键决策(2026-04-15,C12 propose+apply+archive)

### propose 阶段已敲定(4 决策)

- Q1 sample_size=3 / Q2 (C) 标底留 follow-up / Q3 只抓低+30% / Q4 (A) LLM 留 C14
- 注册表扩 10→11(新增 global 型 price_anomaly),DIMENSION_WEIGHTS 调整

### apply 期关键:parse_status='priced' 枚举不存在改 INNER JOIN 语义等价 / EXPECTED_AGENT_COUNT L1 断言 / test_all_dimensions_100_high 追加 price_anomaly OA 项 / L2 Scenario 5 disabled 路径 ctx 带 session 仍写 OA

---

## 2.bak_C11 上上 session 关键决策(2026-04-15,C11 propose+apply+archive)

### propose 阶段已敲定(5 决策,Q5 是第一性原理审新增)

- **Q1 (B) 尾数 (tail_3, int_len) 组合 key**(用户拍板):`PRICE_CONSISTENCY_TAIL_N=3` + 整数位长组合 key,区分 ¥100/¥1100/¥8100(尾数同但量级不同);拒绝纯尾数(选项 A 跨量级误撞)/ N=4(漏报多)/ N=2(误报极高)
- **Q2 币种 + 含税口径完全忽略**(用户拍板):C11 不读 `currency` / `tax_inclusive` 字段,直接按 `total_price / unit_price` 原始值比较;原 execution-plan §3 C11 "口径不一致 → 归一化" 路径简化为"不做归一化",真口径混用场景留 C14 LLM 综合研判
- **Q3 (C) 两阶段对齐**(用户拍板):同模板(sheet 集合相同 + 同名 sheet 行数相同)→ `(sheet_name, row_index)` 位置对齐"同项同价";否则 → `item_name` NFKC 归一精确匹配;拒绝纯位置(非同模板全漏)/ 纯 item_name(漏共享模板信号)/ LLM 语义对齐(留 C14)
- **Q4 (A) 只走 PriceItem,不消费 DocumentSheet**(用户拍板):分层职责清晰 — C5 报价抽取层 / C9 结构层 / C11 报价数值检测层;DocumentSheet 留 C9 专管,C11 不跨层
- **Q5 (A) 纳入 series_relation 子检测**(**第一性原理审 + 用户拍板**):新增第 4 子检测覆盖等差/等比/比例关系;execution-plan §3 C11 原文未列,本 change scope 扩展;水平关系归 C11 / 垂直关系归 C12 语义分层;拒绝留 C12(语义不贴) / 留 follow-up(知道漏不修消极)

### apply 阶段就地敲定

- **现场事实修正**:`currency / tax_inclusive` 字段实际在 `project_price_configs`(项目级 1:1)而非 `price_parsing_rules`(propose 期 design.md 写偏);C11 不读这些字段的决策不变,字段路径修正写入 `backend/README.md`,留作 follow-up 修 spec/design 文本
- **测试 bug 修复一次**:`test_tail_max_hits_limits` 初版用 `Decimal(f"{i}000")` for i in 100..130 全部尾数 "000" 是同一 key,只 1 个 intersect 而非 30;改用 `Decimal(f"1{i:03d}")` 得 30 个不同尾 3 位组合 key
- **scorer 三态 evidence 区分**:`_shape_subdim` 为 disabled / 数据缺失(score=None) / 未执行三态分别填 `enabled / score / reason`;前端按 `enabled=false` 优先识别(对齐 C10 evidence 哨兵语义)
- **Agent 早返路径**:4 flag 全关 → 整 Agent 早返不调 extractor(L1 验证 `ext_mock.assert_not_called()`),贴 C10 风格
- **series 仅同模板时跑**:row_index 对齐不可靠时方差计算无意义;复用 `item_list_detector.is_same_template` helper 单一判定源;非同模板 → `score=None` 子检测 skip,不影响其他子检测
- **series 公式选择**:ratios 用 `statistics.pvariance`(等比 = 比值近常数,方差对绝对尺度不敏感);diffs 用 CV = `pstdev/abs(mean)`(等差 = 差值近常数,但绝对差额尺度差异大,CV 归一化稳)
- **测试目录约定**:8 个 L1 test 文件平级 `tests/unit/test_price_*.py`(对齐 C10 metadata_* 风格);L2 单文件 5 scenario 全覆盖 execution-plan §3 C11 + Q5 新增

### 文档联动

- **`backend/README.md`** 新增 "C11 detect-agent-price-consistency 依赖" 段:13 env + 4 子检测说明 + Q2/Q4 决策注释 + algorithm version `price_consistency_v1`
- **`openspec/specs/detect-framework/spec.md`** sync:MODIFIED "10 Agent 骨架"(dummy 列表去 price_consistency,加"price_consistency 已替换" Scenario;dummy 列表仅剩 3 个 global Agent)+ ADDED 10 Req(共享 extractor / normalizer 契约 / 4 子检测算法契约 / scorer 合成 / Agent 级与行级兜底语义 / evidence_json 结构 / env),total 52 Req
- **`docs/execution-plan.md`** §6 追加 1 行 scope 变更记录:`2026-04-15 | C11 scope 扩 series_relation 子检测 | 第一性原理审暴露遗漏...`;§3 C11 原文保留不改
- **memory 新增 `feedback_first_principles_review.md`**:第一性原理审作为 review 简略版自审第 3 项常驻 checklist,跳出类比惯性挑战 design 本身;Q5 新增子检测就是该规则首次落地产出
- **`.gitignore`** 加 `c11-*` L3 artifacts 白名单
- **`docs/handoff.md`** 即本次更新

---

## 2.bak1 上一 session 关键决策(2026-04-15,C10 propose+apply+archive)

### propose 阶段已敲定(3 决策)

- **Q1 A 合并到一个 change**(用户拍板):3 子 Agent(author/time/machine)合并到一个 change,共用 `metadata_impl/` 子包;拒绝拆 3 mini change
- **Q2 A 扩 C5 持久化 template + 回填**(用户拍板):alembic 0007 加 `document_metadata.template` 列 + parser 扩写 + 回填脚本三件套
- **Q3 A 纯精确匹配 + 轻量 NFKC**(用户拍板):NFKC + casefold + strip 后精确相等;拒绝 Levenshtein / 变体合并 / LLM

### apply 阶段就地敲定

- **alembic revision 字符串缩写**:`0007_add_doc_meta_template`(26 chars)受 `alembic_version.version_num` VARCHAR(32) 限制
- **`_preflight_helpers.bidder_has_metadata` machine 分支 OR 加 template**:宽松判定避免 preflight 过度拦截
- **hit_strength 公式 `|∩|/min(|A|,|B|)` 而非 Jaccard**:贴"围标信号"语义(一方全部命中即 1.0)
- **author 子权重 0.5/0.3/0.2** + **time 子权重 0.7/0.3**(env 可覆盖)
- **`time_detector._slide_window_clusters` 跳过整簇避免重复**(`i = j`)
- **Agent run guard 放宽 `session is None`**:L1 mock extractor 测试需要
- **machine 的 participating_fields 从 hits 反推**:无 sub_scores 字段
- **evidence.enabled 三态**:flag 禁用 → false;数据缺失 → true + participating_fields=[]

### 文档联动

- **`backend/README.md`** 加 "C10 依赖" 段:6 env + 回填脚本用法
- **`openspec/specs/detect-framework/spec.md`** sync:+8 Req(34→42)
- **`openspec/specs/parser-pipeline/spec.md`** sync:+2 Req(15→17)

---

## 2.bak_C10 上上 session 关键决策(2026-04-15,C9 propose+apply+archive)

### propose 阶段已敲定(4 决策)

- **C 选项:跨层延伸 C5 持久化**(用户拍板):新增 `document_sheets` 表 JSONB 持久化 xlsx cell 矩阵 + 合并单元格,不走 "Agent 运行时 re-extract" 路径;明确接受 "C9 跨 2 层"和 "alembic 0006 迁移" 的代价,换长期最干净的数据契约
- **三维度权重 0.4/0.3/0.3**(目录/字段/填充):用户接受 design 默认值,不改均权;run 期 env `STRUCTURE_SIM_WEIGHTS` 可覆盖
- **回填策略:回填**(用户决定):新增 `backend/scripts/backfill_document_sheets.py` 手工触发幂等脚本(NOT EXISTS 过滤 + 单 doc 错误隔离 + `--dry-run`)
- **不引 LLM**(用户接受):三维度纯程序化(LCS / Jaccard / hash);C14 综合研判时再 LLM 串所有维度

### apply 阶段就地敲定

- **`AgentRunResult.score: float` 不放 Optional**(C6 契约锁定):Agent 级"结构缺失"用 `score=0.0` 哨兵 + `evidence.participating_dimensions=[]` 标记;spec 同步从 `score=None` 调到 `score=0.0` 哨兵,2 处 Scenario 已修(spec sync 后已落到 main spec)
- **表名 `document_sheets`(复数)**:design 原写单数 `document_sheet`,apply 期发现既有 `document_texts/document_images` 全复数 → 改齐;同时 FK 不加 CASCADE(对齐既有,虽 design.D1 原写了 ondelete="CASCADE")
- **`_preflight_helpers.bidders_share_role_with_ext` 新增**:preflight 第二步要 "至少一侧有 docx 或 xlsx",独立 helper 比内联查询干净
- **目录 + xlsx 维度可能落不同 file_role**(structure_similarity 内决策):evidence.doc_role 用 `"role_a+role_b"` 合并表达;doc_id_a / doc_id_b 用 `int[]`(可能 1 或 2 个)而非单 int
- **维度级 skip 下放到 run 内**(spec D8 已写,落到代码):preflight 不做真章节切分 / cell 矩阵读取(成本高),只做轻量 COUNT 检查
- **测试目录约定灵活**:tasks.md 原写部分 L1 测试在 `tests/unit/services/parser/...`,apply 时改放到 `tests/unit/test_*.py` 平级(与既有 `test_parser_content_xlsx.py` 等对齐);xlsx 持久化测试合并到既有 `tests/e2e/test_parser_content_api.py`(L2)而非新建 L1 文件,匹配既有 extract_content 测试位置
- **`fixtures/auth_fixtures._delete_all` 同步加 DocumentSheet** 清表(否则 C9 后 PairComparison 测试因 BidDocument 删除受 FK 阻塞)
- **回填脚本独立 session per doc**:每个 doc 自己 `async with async_session()` + commit + 失败 rollback 不影响其他;比一个长事务里 `try/except` 干净
- **bool 归 'T' 文本**(fill_pattern 决策):True/False 通常是配置开关而非数值,与 N(数字)区分;改善"模板填充模式"语义
- **`_row_bitmask` 尾部连续 0 截掉**:稀疏 sheet 干扰大,对齐两侧(否则同结构但宽度不同 → bitmask 长度差 → multiset 不匹配)

### 文档联动

- **`backend/README.md`** 新增 "C9 detect-agent-structure-similarity 依赖" 段:5 新 env + DocumentSheet 持久化说明 + 回填脚本两种用法(全量 / dry-run)
- **`openspec/specs/detect-framework/spec.md`** sync:MODIFIED "10 Agent 骨架"(dummy 列表去 `structure_similarity`,加 "已替换" Scenario)+ ADDED 5 Req(三维度算法 / preflight / 维度级与 Agent 级 skip 语义 / evidence_json / 环境变量),+ 17 Scenario;total 34 Req
- **`openspec/specs/parser-pipeline/spec.md`** sync:MODIFIED "文档内容提取"(xlsx 分支加 DocumentSheet 双写 + 裁切)+ ADDED 3 Req(DocumentSheet 数据契约 / 回填脚本 / xlsx_parser merged_cells_ranges)
- **`.gitignore`** 加 `c9-*` L3 artifacts 白名单
- **`docs/handoff.md`** 即本次更新

---

## 2.bak_C8 上上上 session 决策(2026-04-15,C8 apply+archive)

### propose 阶段已敲定(4 决策)

- **A1 独立降级**:章节切分失败 → C8 自己跑整文档 TF-IDF + dimension 仍写 section_similarity
- **B1 纯正则 5 PATTERN 切章**:第X章 / 第X节 / X.Y 数字 / 中文数字+顿号 / 纯数字+顿号
- **C2 title TF-IDF + 序号回退对齐**:title sim ≥ 0.40 贪心配对;未配对按 idx 序号回退
- **D1 复用 C7 `text_sim_impl/`**:C7 子包只读 import,零改动

### apply 阶段就地敲定

- **`_title_tokenizer` 独立**(aligner.py):C7 jieba_tokenizer 短 title 归零;C8 加专用宽松 tokenizer
- **`raw_loader.py` 绕 segmenter 短段合并**:保章节标题独立边界
- **pair 级公式 = max×0.6 + mean×0.4**:章节粒度 max 更易虚高,mean 权重上调对冲
- **章节对合并跨 LLM 调用**:所有章节 para_pairs 合并按 title_sim × avg_sim 粗排,仅前 30 段对送 LLM

---

## 3. 待确认 / 阻塞

- 无硬阻塞,**M3 进度 8/9**,C13 已 archive,本次 commit 后进 C14 收官
- **Follow-up(C13 新增)**:**L3 手工凭证待补**(延续 C5~C12):Docker kernel-lock 解除后,按 `e2e/artifacts/c13-2026-04-15/README.md` 步骤跑 6 张截图(启动检测 / error_consistency 铁证 evidence 展开 / error_consistency downgrade 展开 / image_reuse MD5+pHash evidence 展开 / style 三 bidder consistent_groups 展开 / 任一 LLM 失败兜底 banner)
- **Follow-up(C13 新增)**:**image_reuse L-7 非通用图 LLM 回填铁证**:evidence 占位 `llm_non_generic_judgment=null` 已就绪;C14 综合研判 或 独立 follow-up change 回填 L-7 LLM 判断通用 logo / 罕见瑕疵图 → 铁证升级
- **Follow-up(C13 新增)**:**style >20 bidder 完整跨组算法**:本期简化版每组 ≤20 不跨组比,实战若项目 bidder 数密集 > 20 且需要跨组信号,需完整分组算法(如 TF-IDF 聚类 / bidder 两两概率上限去重)
- **Follow-up(C13 新增)**:**C14 LLM 回填 error_consistency / image_reuse / style evidence.llm_explanation**:三 Agent 都预留 `llm_explanation=null`,C14 综合研判时回填高层解释(为什么认定/为什么不认定围标)
- **Follow-up(C13 新增)**:**document_texts 行级 vs JSONB 数组文本修正**:spec 文本写 "paragraphs / header_footer JSONB 数组",实际 DocumentText 是行级表(location 字段);代码已对,只是 spec 文本需下次 cleanup(可与 C11 字段路径偏差一并修)
- **Follow-up(C13 新增)**:**error_consistency L-5 prompt 调优**:apply 期简版 system prompt,实战若假阳偏高/漏判偏多,按 requirements §L-5 原文精细化 prompt(加 N-shot examples / 输出格式约束)
- **Follow-up(C12 留下)**:**L3 手工凭证待补 c12-2026-04-15**(kernel-lock 依赖);标底路径实施 / direction=high/both / 项目类型区分阈值 / robust 中位数+IQR
- **Follow-up(C11 留下)**:**L3 手工凭证 c11 + 字段路径偏差修 / series 阈值调参 / LLM 语义对齐 item_name / 含税币种混用漏报留 C14 / series robust 法**
- **Follow-up 细则**(C12/C11 旧 follow-up 归档后去 `git log` 查详情)
- **Follow-up(C10 留下)**:**生产回填 template 字段**:M3 完成后生产部署前必须跑一次 `backfill_document_metadata_template.py` 回填历史文档;未回填的文档 metadata_machine 维度全 skip
- **Follow-up(C10 留下)**:**作者变体合并** + **template 路径归一化** + **时间窗 5 分钟调优**:实战数据反馈后再处理
- **Follow-up(C9 留下,C10/C11 继承)**:**L3 手工凭证待补 c9-2026-04-15**(同上 kernel-lock 依赖);合并单元格细粒度比对 / sheet 名 fuzzy 匹配 / document_sheets.rows_json 巨型存储 / STRUCTURE_SIM_WEIGHTS 调优
- **Follow-up(C8 留下,C9/C10/C11 继承)**:**L3 手工凭证待补 c8-2026-04-15**(同上 kernel-lock 依赖)
- **Follow-up(C7 留下,C8/C9/C10/C11 继承)**:`ProcessPoolExecutor` executor cancel 无法真中断子进程任务(C6 Risk-1);用 `max_features + MAX_PAIRS + MAX_ROWS` 限时缓解
- **Follow-up(C7 留下,C8/C9/C10/C11 继承)**:容器 `cpu_count` 验证(C6 Q3);kernel-lock 解除后跑 `docker exec backend python -c "import os; print(os.cpu_count())"`
- **Follow-up(C6 留下,C13 消化 11/11)**:11 Agent 真实 `run()` 全部替换完毕 — text_similarity(C7)/ section_similarity(C8)/ structure_similarity(C9)/ metadata_author+time+machine(C10)/ price_consistency(C11)/ price_anomaly(C12)/ error_consistency+image_reuse+style(C13),dummy 列表清空
- **Follow-up(C6 留下)**:`judge.py` `DIMENSION_WEIGHTS` 占位权重,C14 LLM 综合研判时可调
- **Follow-up(C4 留下)**:加密包 3 次密码错冻结(推 C17);`encrypted-sample.7z`(L3 fixture)未入库
- **Follow-up**:Docker Desktop kernel-lock — C3~C11 L3 都跑不起来
- **Follow-up**:生产部署前必须 env 覆盖 `SECRET_KEY` / `AUTH_SEED_ADMIN_PASSWORD` / `LLM_API_KEY`;C6 `AGENT_TIMEOUT_S` 等;C7 `TEXT_SIM_*` 3 / C8 `SECTION_SIM_*` 3 / C9 `STRUCTURE_SIM_*` 5 / C10 `METADATA_*` 6 / C11 `PRICE_CONSISTENCY_*` 13 / C12 `PRICE_ANOMALY_*` 7 / **C13 `ERROR_CONSISTENCY_*` 5 + `IMAGE_REUSE_*` 5 + `STYLE_*` 6**
- **Follow-up(C5 留下)**:`role_keywords.py` Python 常量;C17 admin 后台迁 DB + UI
- **Follow-up(C9 pre-existing 暴露,C10/C11 继承未处理)**:`backend/app/services/parser/content/__init__.py` 有 2 条 ruff 错(F401 unused `select` + 一行 E501)pre-existing,留 cleanup change(可与 C11 字段路径偏差修一起)

---

## 4. 下次开工建议

**一句话交接**:
> **C13 `detect-agents-global` 已归档,M3 进度 8/9**。L1+L2 = **883 全绿**,C13 新增 140 用例;L3 延续手工凭证。**11 Agent 全部替换为真实算法,dummy 列表清空**;`error_consistency` L-5 LLM 铁证能力本期兑现;`judge.py` 扩读 OverallAnalysis.evidence_json.has_iron_evidence 支持 global 型铁证升级。下一步 `git push`(本次 archive commit 已产生),然后进 **C14 `detect-llm-judge`**(M3 收官,judge 占位 regex → LLM 综合研判)。

**可直接粘贴给 AI 作为新会话起点**:
```
继续 documentcheck 项目。M3 进度 8/9,C13 detect-agents-global 已 archive + commit + push。
下一步进 C14 /opsx:propose detect-llm-judge(M3 收官)
  - 职责:judge.py 的占位 regex 综合研判 → LLM 综合研判(requirements §L-9)
  - 输入:所有 PairComparison + OverallAnalysis(11 维度分数 + 各自 evidence_json + 铁证标记)
  - 输出:AnalysisReport.llm_conclusion(现 "" 留空 → LLM 生成自然语言结论)+ 可选调整 total_score / risk_level
  - 不动:11 Agent 注册表 / 3 子包(error_impl/image_impl/style_impl/price_impl/anomaly_impl/metadata_impl/structure_sim_impl/section_sim_impl/text_sim_impl)/ AgentRunResult 3 字段契约
  - 可能动:judge.py compute_report / judge_and_create_report / judge 新增 llm_client.py 子模块 / DIMENSION_WEIGHTS 按实战调整
  - 可复用 C13 模式:LLM mock 单一入口 llm_mock.py + JSON 解析容错 + 重试 + 失败兜底 skip 哨兵
对应 docs/execution-plan.md §3 C14 小节(已 §6 改名为 detect-llm-judge)。
请先读 docs/handoff.md 确认现状(M3 进度 8/9 / C13 留下的 follow-ups / 11 Agent 真实算法全就绪 / judge.py has_iron_evidence 读 OA 已扩)。
propose 阶段需用户敲定(产品/范围级):
  - C14 输入粒度:喂全部 11 维度 evidence_json 还是预聚合摘要(控 token)
  - C14 LLM 失败兜底:原 regex 路径保留还是删掉
  - LLM conclusion 是否覆盖 total_score(改评分)还是仅补 llm_conclusion 文本
  - 是否做跨项目历史库 read(execution-plan §3 原 C14 = history_cooccur 作废,但"跨项目"作为 LLM 上下文仍可选)
也检查 memory 和 claude.md。
```

**C14 前的预备条件(已就绪)**:

- **11 Agent 真实算法全就绪**:text/section/structure sim + 3 metadata + 2 price + 3 global(error/style/image)
- **判别层接口**:`judge.compute_report(pair_comparisons, overall_analyses) -> (total, level)`,C14 在此基础上叠 LLM 层
- **铁证传递契约**:pair 走 `PairComparison.is_ironclad`,global 走 `OverallAnalysis.evidence_json["has_iron_evidence"]`(C13 已扩 judge.py 读)
- **LLM mock 共享入口**:`tests/fixtures/llm_mock.py` 已覆盖 L-1/L-2/L-4/L-5/L-8,C14 加 L-9(综合研判)
- **llm_conclusion 字段空位**:`AnalysisReport.llm_conclusion` 目前 `""`,C14 填

---

## 5. 最近变更历史(仅保留最近 5 条)

| 日期 | 变更 |
|---|---|
| 2026-04-15 | **C13 `detect-agents-global` 归档(M3 进度 8/9)**:**11 Agent 真实算法全就位,dummy 列表清空**;**检测层**:新增 3 子包共 18 文件(`error_impl/` 7 + `image_impl/` 5 + `style_impl/` 6);重写 3 Agent run()(`error_consistency` 5 层兜底 + L-5 LLM 铁证;`image_reuse` MD5+pHash 双路不升铁证;`style` L-8 两阶段全 LLM,>20 bidder 自动分组);**`_preflight_helpers.bidder_has_identity_info`** 新增;**`judge.py::compute_report`** +3 行读 `OverallAnalysis.evidence_json["has_iron_evidence"]` 支持 global 型铁证升级;**`llm_mock.py`** 扩 L-5 + L-8 两阶段 9 builder/fixture;**测试 883 全绿**(C13 新增 140 用例:L1 131 + L2 8 + 注册表 1);**5 决策**:Q1 合并 / Q2 (A) L-5 铁证 / Q3 (C) MD5+pHash 双路 / Q4 (C) L-8 全 LLM / Q5 零新增依赖;apply 现场:不扩 AgentRunResult NamedTuple 改走 OA evidence 顶层 has_iron_evidence / preflight 任一缺 → downgrade 回贴 spec 原语义 / DocumentText 行级 SQL(非 JSONB) / imagehash int64 cast / 3 既有测试调整(judge evidence_json getattr 保护 / timeout test monkeypatch error_consistency slow run / dummy_global_run test 补写 OA);spec sync +14 ADDED + 1 MODIFIED Req(detect-framework 50→64)含手动修正 5 处 is_iron_evidence 契约;execution-plan §6 追加 2 行(C13/C14 改名);L3 延续手工凭证(c13-2026-04-15 占位 6 张截图) |
| 2026-04-15 | **C12 `detect-agent-price-anomaly` 归档(M3 进度 7/9,commit f04eb30)**:**注册表扩 10→11**(新增 global 型 `price_anomaly`):registry.py 加 `EXPECTED_AGENT_COUNT=11` 常量 + agents/__init__.py 加 import;**检测层**:新增 `anomaly_impl/` 6 文件(__init__ 含 `write_overall_analysis_row` 对齐 C11 / config 7 env + AnomalyConfig + 严格/宽松两类校验 / models 三 TypedDict / extractor 单次 SQL INNER JOIN 聚合 + bidder_id 升序 + max_bidders 截断 + 软删排除 / detector mean 计算 + deviation 判定 + mean==0 兜底 + direction 非 low fallback+warn / scorer 占位 min(100, N*30+max(|dev|)*100))+ `price_anomaly.py` Agent 三层兜底(ENABLED=false 早返 / preflight skip / run 边缘 skip 哨兵);**`_preflight_helpers.project_has_priced_bidders`** 单次 COUNT(DISTINCT) + INNER JOIN 自动过滤;**judge.py DIMENSION_WEIGHTS** 调整(+price_anomaly=0.07 / price_consistency 0.15→0.10 / image_reuse 0.07→0.05);**测试 743 全绿**(C12 新增 49 用例:L1 43 + L2 5 + 注册表 1);**4 决策**:Q1 sample_size=3 / Q2 (C) 标底留 follow-up / Q3 只抓低+30% / Q4 (A) LLM 留 C14;apply 现场:parse_status='priced' 非 Bidder 枚举值改用 INNER JOIN 语义 / EXPECTED_AGENT_COUNT 不在模块加载期 assert 改测试断言 / test_all_dimensions_100_high 追加 price_anomaly OA 项修 93→100 / PriceParsingRule project 级非 document 级 fixture 修复 / L2 Scenario 5 disabled 路径仍写 OverallAnalysis 断言移 L1;spec sync +5 ADDED+3 MODIFIED Req(detect-framework 52→57);execution-plan §6 追加 C12 注册表扩展记录;L3 延续手工凭证 |
| 2026-04-15 | **C11 `detect-agent-price-consistency` 归档(M3 进度 6/9,commit 94e8f18)**:**检测层**:新增 `price_impl/` 11 文件(__init__ 含 write_pair_comparison_row 复用 C10 / config 13 env + 4 子检测 dataclass / models TypedDict / normalizer NFKC + Decimal split_price_tail truncate+zfill / extractor 按 sheet 分组+预计算 / 4 detector(tail (tail_3,int_len) 组合 key 防量级误撞 / amount_pattern (item_name,unit_price) 对精确匹配 / item_list 两阶段对齐"同项同价"+item_name 兜底 / **series_relation Q5 第一性原理审新增** 同模板对齐序列 ratios 方差+diffs CV 双路命中) / scorer 4 子检测加权合成,disabled/None 不参与归一化)+ 重写 `price_consistency.py::run()`(4 flag 全关早返;Agent 级 skip score=0.0+participating_subdims=[] 哨兵);**测试 694 全绿**(C11 新增 69 用例:L1 64 + L2 5);零 LLM 引入;**5 决策**:Q1 (B) 尾数组合 key / Q2 币种含税完全忽略 / Q3 (C) 两阶段对齐 / Q4 (A) 只走 PriceItem / **Q5 (A) 第一性原理审新增 series**;apply 意外:测试构造 bug 修一次 / 现场发现字段实际在 project_price_configs(留 cleanup) / scorer 三态 evidence(disabled/None/未执行)/ Agent 早返路径;spec sync +10 ADDED+1 MODIFIED Req(detect-framework 42→52);execution-plan §6 追加 C11 scope 扩展记录;**memory 新增 `feedback_first_principles_review.md`**(自审常驻第 3 项);L3 延续手工凭证 |
| 2026-04-15 | **C10 `detect-agents-metadata` 归档(M3 进度 5/9,commit 7573deb)**:**数据层延伸**:扩 `DocumentMetadata.template` 字段 + alembic 0007 + parser 扩 + 回填脚本;**检测层**:新增 `metadata_impl/` 9 文件 + 重写 3 Agent run()(author 三字段精确聚类 hit_strength=`|∩|/min` / time modified 5min 滑窗 + created 精确相等 / machine 三字段元组精确碰撞);**测试 625 全绿**(C10 新增 75 用例);零 LLM 引入;关键决策:合并一个 change / 扩 C5 持久化 + 回填 / 纯精确 + NFKC;spec sync +8 Req(detect-framework 34→42)+ 2 Req(parser-pipeline 15→17) |
| 2026-04-15 | **C9 `detect-agent-structure-similarity` 归档(M3 进度 4/9,commit 8bbda15)**:**数据层延伸**:新增 `document_sheets` 表 + alembic 0006 + 回填脚本;**检测层**:新增 `structure_sim_impl/` 8 文件 + 重写 `structure_similarity.py::run()` 三维度纯程序化(目录 LCS / 字段 Jaccard / 填充 Jaccard);**测试 550 全绿**(C9 新增 103 用例);零 LLM 引入;关键决策:C 选项跨层延伸持久化;spec sync +5 Req(detect-framework)+ 3 Req(parser-pipeline) |
