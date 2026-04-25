## ADDED Requirements

### Requirement: 模板簇识别(template cluster detection)

系统 SHALL 在 `judge.judge_and_create_report` 内、PC/OA 加载完成后、第一次 `_compute_dims_and_iron`(供 DEF-OA 写入)与 `_apply_template_adjustments` 调用之间执行模板簇识别,识别结果用于后续维度剔除与降权。识别动作不依赖 `compute_report`(production path 不调 `compute_report`,该函数仅作纯函数测试入口)。

识别规则:
1. 每个 bidder 收集其名下 `file_role in {"technical", "construction", "bid_letter", "company_intro", "authorization", "pricing", "unit_price"}` 的全部 BidDocument 对应的 DocumentMetadata 行;`file_role` 枚举值与 `parser/llm/role_classifier.py::VALID_ROLES` 对齐;**排除** `qualification`(PDF 营业执照等 author 常为"Admin"通用值噪音)+ `other`(无效分类)
2. 对每个 DocumentMetadata,构造 cluster_key = `(nfkc_casefold_strip(author), doc_created_at_utc_truncated_to_second)`;`nfkc_casefold_strip` 复用 `app.services.detect.agents.metadata_impl.normalizer.nfkc_casefold_strip`(NFKC 全角→半角 + casefold 大小写归一 + strip 两端空白),与 `metadata_author` agent 内部 author 比较语义对齐(防全角/大小写差异下 agent 判同 + iron=true 但 cluster 不命中导致抑制失效);任一字段为 NULL/空 → 该文档跳过(不参与识别),记 WARNING 日志 `template_cluster: bidder=<id> doc=<id> key incomplete`
3. `doc_created_at` 归一化:`dt.astimezone(timezone.utc).replace(microsecond=0)`;naive datetime 视为 UTC 后再归一(防 aware/naive 混用时 `==` 比较失败)
4. Bidder `i` 的 key 集合 `S_i = {(author_norm, created_at_norm), ...}`
5. 两个 bidder `i, j` 满足 `S_i ∩ S_j ≠ ∅` → 判同簇
6. 簇是等价类(A-B 同簇 + B-C 同簇 → A-B-C 同簇,实施用 union-find,bidder 数 N≤20 规模 O(N²) 可接受)
7. 等价类需 **≥ 2 bidder** 才构成有效簇;1-bidder 单点不成簇
8. `hash_sha256` **不**参与 cluster_key(投标方改内容导致哈希易变,误识别率高)

识别函数签名:`_detect_template_cluster(bidder_metadata_map: dict[int, list[DocumentMetadata]]) -> list[TemplateCluster]`,纯函数,位于 `backend/app/services/detect/template_cluster.py`;`bidder_metadata_map` 由调用方按 file_role 过滤后传入,函数本身不查 DB。

**已知遗留缺陷(预存量,本 Req 不治)**:`metadata_*` agent 内部 `extract_bidder_metadata` 不按 file_role 过滤,会扫 qualification 等噪音;follow-up 处理。

**失败兜底**:metadata 查询异常或全 NULL → 返空 list + ERROR 日志;judge 流水线继续走原打分路径,不阻塞检测。

#### Scenario: 3 bidder 同 metadata 全命中簇

- **WHEN** project 3 个 bidder(A/B/C)各有一份技术标 docx(file_role=technical),DocumentMetadata 均为 `author="LP" + doc_created_at="2023-10-09 07:16:00+08:00"`(北京时间)
- **THEN** `_detect_template_cluster` 返回 1 个 cluster,`cluster.bidder_ids=[A, B, C]`,`cluster_key_sample={"author":"lp","created_at":"2023-10-08T23:16:00+00:00"}`(author 经 nfkc_casefold_strip 归一化为小写,created_at 归一化为 UTC)

#### Scenario: bidder 有多份文档集合相交判簇

- **WHEN** bidder A 有 2 份文档 metadata `[(LP, t1), (LP, t2)]`(技术标 + 投标函);bidder B 有 1 份 `[(LP, t1)]`
- **THEN** `S_A ∩ S_B = {(LP, t1)}` 非空 → A-B 同簇

#### Scenario: file_role=qualification 不参与

- **WHEN** bidder A 的技术标 metadata=(LP, t1),营业执照 PDF metadata=(Admin, t0);bidder B 的技术标 metadata=(Admin, t0),qualification metadata=(XYZ, t2)
- **THEN** A 只贡献 `{(LP, t1)}`(qualification 被过滤);B 只贡献 `{(Admin, t0)}`;两 bidder 的 S 不相交 → **不**判同簇。Admin/t0 虽然在 A 的 qualification 中出现但因 file_role 被过滤,不参与识别

#### Scenario: 2 bidder 同模板 + 1 bidder 独立

- **WHEN** 3 bidder,A/B 技术标 metadata=(LP, t1);C 技术标 metadata=(XYZ, t2)
- **THEN** 返回 1 cluster,bidder_ids=[A, B];C 不属于任何簇

#### Scenario: metadata author NULL → 该文档跳过

- **WHEN** bidder A 的所有 cluster 范围内文档 metadata.author 均为 NULL
- **THEN** A 的 `S_A` 为空;A 不参与任何簇识别;日志 WARNING `template_cluster: bidder=A all keys incomplete`;A 所有 pair 走原打分路径

#### Scenario: aware vs naive datetime 视为同一瞬间

- **WHEN** bidder A metadata.doc_created_at 为 `datetime(2023,10,9,7,16,0,tzinfo=UTC)`;bidder B 为 naive `datetime(2023,10,9,7,16,0)`(被视为 UTC)
- **THEN** 归一化后两值相等;若 author 也一致则判同簇

#### Scenario: 1 bidder 项目返空

- **WHEN** project 只有 1 个 bidder
- **THEN** `_detect_template_cluster` 返空 list(无法构成跨 bidder 等价类)

#### Scenario: 所有独立不成簇返空

- **WHEN** 所有 bidder 的 S 两两不相交
- **THEN** 返空 list

#### Scenario: 传递闭包合并

- **WHEN** A-B 同簇(共享 key1);B-C 同簇(共享 key2),但 A-C 无直接交集
- **THEN** union-find 合并为单簇 `bidder_ids=[A,B,C]`;cluster_key_sample 任选其一(如 key1 或 key2)

#### Scenario: metadata 查询异常不阻塞

- **WHEN** DB 查询 `document_metadata` 抛异常
- **THEN** `_detect_template_cluster` 返空 list + 写 ERROR 日志;judge 流水线继续


### Requirement: 模板簇维度剔除/降权与铁证抑制

识别出模板簇后,`judge.judge_and_create_report` MUST 调用 `_apply_template_adjustments(pcs, oas, clusters)` 构造 `(adjusted_pcs, adjusted_oas, adjustments)` 三元组并下发到 `_compute_dims_and_iron` / `_has_sufficient_evidence`(详见 MODIFIED "证据不足判定规则")/ `summarize`(经 `_run_l9` 透传)各 helper(均通过本 change 扩展的 keyword-only `adjusted_pcs / adjusted_oas` 可选参数消费),缺失回落 ORM 原值;adjustment 清单写入 `AnalysisReport.template_cluster_adjusted_scores`,**不回写 DB**(PC/OA 表行保留 agent 写入的原始 score / is_ironclad / evidence_json,符合审计原则)。

**`compute_report` 自身签名/语义保持不变**(主 spec L268 + L2843 既有契约保留);本 ADD Req 不修改主 spec L268 的 `compute_report` 契约(防 archive sync 时误改纯函数测试入口的签名)。

**剔除(adjusted_score=0 + is_ironclad 抑制)** 四维:

1. `structure_similarity` PairComparison:pair 两端 bidder 均在**同一个**簇 → adjusted_score=0.0,adjusted_is_ironclad=false,evidence_extras `{template_cluster_excluded: true, raw_score: <orig>, raw_is_ironclad: <orig>}`
2. `metadata_author` PC:同上(铁证源是模板 author=LP 不是围标;`metadata_impl/author_detector.py` 在 score≥85 时写 is_ironclad=true,抑制条款非空操作)
3. `metadata_time` PC:同上(`metadata_impl/time_detector.py` 在 created_at 完全相等时可能 score≥85 + is_ironclad=true;同一信号既识别污染又计分,必须抑制)
4. `style` OverallAnalysis(global):**全覆盖判定**(round 7 reviewer M4 锁产品语义)= `len(clusters)==1 and 该簇 bidder_ids == project 全部 bidder_ids`(单一簇覆盖全部 bidder)→ OA adjusted_score=0.0,evidence_extras `{template_cluster_excluded_all_members: true, raw_score: <orig>}`;否则(部分 bidder 在簇 / 多簇并存即使各簇都覆盖 / 单簇但只覆盖部分)→ **保留原分**(先期简化,N-gram 留 follow-up,见 R5);**注**:`style.py::_build_evidence` 不输出 `has_iron_evidence` 字段(本期 style 不写 iron),抑制 `has_iron_evidence` 实际为 no-op,但 evidence_extras 仍标 `excluded_all_members=true` 用于 observability

**降权(adjusted_score = raw × 0.5)** 一维 + 铁证豁免:

5. `text_similarity` PC:pair 两端同簇 → adjusted_score = `round(raw * 0.5, 2)`,evidence_extras `{template_cluster_downgraded: true, raw_score: <orig>}`
6. **铁证豁免**:若该 PC `is_ironclad=true`(`text_sim_impl/aggregator.py::compute_is_ironclad`:LLM 段级判定 plagiarism 段数 ≥3 或 plagiarism 占比 ≥50%,LLM 主动区分 template/plagiarism,iron=true 时即"模板外仍有大量真抄袭")→ **不降权保留原分**,evidence_extras `{template_cluster_downgrade_suppressed_by_ironclad: true, raw_score: <orig>}`,adjusted_is_ironclad 保持 true(is_ironclad 不被抑制,铁证独立有效)

**不受影响维度**(adjusted_score 沿用 raw + is_ironclad 沿用 raw):
- `section_similarity` / `metadata_machine` / `price_consistency` / `price_anomaly` / `image_reuse` / `error_consistency`(共 6 维;加上剔除 4 维 + 降权 1 维 = 11 维全覆盖)
- 各维度 is_ironclad/has_iron_evidence 写入事实(影响 fixture 真实性):
  - PC.is_ironclad 由以下 agent 写:`metadata_author` / `metadata_time` / `metadata_machine` / `text_similarity`(LLM plagiarism)/ `section_similarity` / `structure_similarity` / `price_consistency`
  - OA.evidence_json.has_iron_evidence 由 `error_consistency` + DEF-OA 聚合行(从 PC.is_ironclad 聚合)写
  - **`image_reuse` 与 `style` 本期不写 iron**(`image_reuse.py:9` "is_iron_evidence 始终 False" + `style.py::_build_evidence` 无 has_iron_evidence)— 涉及这两个 agent 的 fixture 不能假设原 iron=true

铁证字段总体原则:
- 剔除的 4 维:`is_ironclad` / `has_iron_evidence` 必须抑制为 false(铁证源是模板固有,不是围标信号)
- 降权的 text_similarity:`is_ironclad` 若原为 true 则保持 true 且降权豁免
- 不受影响维度:沿用 raw 不动

**可观测性记录**:每条 adjustment 写入 `AnalysisReport.template_cluster_adjusted_scores.adjustments` 数组,统一 shape 含 `scope` 字段区分三类 entry:

```json
{
  "scope": "pc" | "global_oa" | "def_oa",
  "pair": [bidder_id_1, bidder_id_2] | null,    // scope="pc" 时必填,其他场合 null
  "oa_id": <int> | null,                          // scope="global_oa" / "def_oa" 时必填,scope="pc" 时 null
  "dimension": "<dim_name>",
  "raw_score": <float>,
  "adjusted_score": <float>,
  "raw_is_ironclad": <bool> | null,               // PC 维度填 bool;global_oa(style)/ def_oa 无此字段填 null
  "raw_has_iron_evidence": <bool> | null,         // OA 维度填 bool;PC 维度填 null
  "reason": "template_cluster_excluded" | "template_cluster_downgraded" | "template_cluster_excluded_all_members" | "template_cluster_downgrade_suppressed_by_ironclad" | "def_oa_aggregation_after_template_exclusion"
}
```

scope 语义:
- `"pc"` — PairComparison 行的 adjustment(structure_similarity / metadata_author / metadata_time / text_similarity 受污染 pair)
- `"global_oa"` — 原生 global agent OA 行的 adjustment(本 change 仅 style 在全覆盖时进入此类)
- `"def_oa"` — 受污染维度的 DEF-OA aggregation OA 行的 adjustment(score=`max(adjusted PC scores)`,has_iron_evidence=`any(adjusted PC.is_ironclad)`)

总 entry 数 = scope=pc 数 + scope=global_oa 数 + scope=def_oa 数。例:3 bidder 全簇 prod fixture → 12 个 pc(structure×3 + metadata_author×3 + metadata_time×3 + text×3)+ 1 个 global_oa(style)+ 4 个 def_oa(structure / metadata_author / metadata_time / text 各 1)= **17 条**。

`AnalysisReport.template_cluster_detected = (len(adjustments) > 0)`,BOOLEAN NOT NULL DEFAULT FALSE。

**adjusted dict 数据契约**(具体调用顺序与 helper 实施手法见 design.md D5 / D7):
- `AdjustedPCs = dict[int, dict]`(key = pc.id)+ `AdjustedOAs = dict[int, dict]`(key = oa.id)拆开,避免两表 PK 取值重叠错位
- `_apply_template_adjustments` MUST 同时为受污染维度的 PC.id **与** DEF-OA OA.id 产 entry;DEF-OA entry 中 `score = max(全集 adjusted-or-raw PC scores)`,`has_iron_evidence = any(全集 adjusted-or-raw PC.is_ironclad)`(全集含 in-cluster 受调整 + out-of-cluster 沿用 raw + 铁证豁免保留 raw 三类 PC)
- `_apply_template_adjustments` 区分 DEF-OA vs 原生 global OA 按 `oa.dimension in PAIR_DIMENSIONS`:in → `scope="def_oa"`;out → `scope="global_oa"`(本 change 仅 style 进入此类)

**关键 invariant**(实施期 MUST 保证):
1. **raw 入库 / adjusted 算分**:DB 中 PC/OA 行的 score / is_ironclad / evidence_json 保留 agent 写入的原始值(D7 审计要求);`_compute_formula_total / _has_sufficient_evidence / summarize` 等下游消费的是 adjusted dict + raw 回落的组合
2. **`compute_report` 签名/语义保持不变**(主 spec L268 + L2843 既有契约 + 现有 L1 signature_unchanged 测试);本 ADD Req 不修改主 spec L268 的 `compute_report` 契约
3. **无 cluster 命中(`adjustments==[]`)行为完全等价 change 前**:helper 全部传 None,走原 AgentTask 分母 + raw per_dim_max
4. **DEF-OA local list 同步**:DEF-OA 写入步骤 `session.add(oa)` 后 MUST 同步 `overall_analyses.append(oa)`;调用 `_has_sufficient_evidence` 时 list 长度 == 11(4 global + 7 pair)

#### Scenario: 3 bidder 全在同簇 → structure pair 全剔 + is_ironclad 抑制

- **WHEN** 3 bidder 全在同簇;structure_similarity 产出 3 对 PC(A-B=100 iron=true, A-C=100 iron=true, B-C=100 iron=true)— 与 prod 真实形态对齐(`structure_sim_impl/scorer.py:74-77` 在 max_sub≥0.9 且 score≥85 时写 iron=true);DEF-OA structure_similarity 写入 `score=100, has_iron_evidence=true`(从 raw PC 聚合)
- **THEN** 3 条 PC adjustment + 1 条 DEF-OA OA adjustment 记录写入;`adjusted_pcs[pc.id]={"score":0, "is_ironclad":false, "evidence_extras":{"raw_score":100, "raw_is_ironclad":true, "template_cluster_excluded":true}}` × 3;`adjusted_oas[def_oa.id]={"score":0, "has_iron_evidence":false, "evidence_extras":{"raw_score":100, "raw_has_iron_evidence":true}}`;helper 读到 `per_dim_max["structure_similarity"]=0`,iron 集合不含 structure_similarity

#### Scenario: metadata_author 带铁证被剔且抑制

- **WHEN** 3 bidder 全在同簇;metadata_author 产出 3 对 PC 均 score=100 + is_ironclad=true(`metadata_impl/author_detector.py` 阈值 85 触发)
- **THEN** adjusted_score=0 + adjusted is_ironclad=false(**全部**被抑制);adjustment.raw_is_ironclad=true 写入 JSONB 供审计;`_compute_dims_and_iron` 扫到的 is_ironclad=false;`has_ironclad=False`(其他维若也被抑制);`_compute_formula_total` 不触发 `max(total, 85.0)`;`_has_sufficient_evidence` 铁证短路不命中

#### Scenario: metadata_time 带铁证被剔且抑制

- **WHEN** 3 bidder 全在同簇;metadata_time PC 因 created_at 完全相同 sub_score=1.0 + agent 层面 is_ironclad=true
- **THEN** adjusted_score=0 + adjusted is_ironclad=false;adjustment 记录 raw_is_ironclad=true

#### Scenario: style 全覆盖 → OA 剔除

- **WHEN** 3 bidder 全在某一簇,style OA score=76.5(style 不写 has_iron_evidence)
- **THEN** adjusted_score=0;adjustment `{pair:null, dimension:"style", raw_score:76.5, raw_is_ironclad:false, reason:"template_cluster_excluded_all_members"}`

#### Scenario: style 部分覆盖 → 保留原分(先期简化)

- **WHEN** 3 bidder,A/B 在簇,C 独立;style OA score=80
- **THEN** adjusted_score=80(保持);无 style adjustment 记录

#### Scenario: text_sim 降权 ×0.5 无铁证

- **WHEN** A-B 在同簇,text_similarity PC A-B raw=91.59 is_ironclad=false
- **THEN** adjusted_score=45.80(`round(91.59 * 0.5, 2)`);adjustment.reason="template_cluster_downgraded"

#### Scenario: text_sim 有铁证触发降权豁免

- **WHEN** A-B 在同簇,text_similarity PC A-B raw=95.0 is_ironclad=true(LLM 段级判定 ≥3 段或 ≥50% plagiarism,而非 template)
- **THEN** adjusted_score=95.0(**不**降权);adjusted is_ironclad=true 保留;adjustment.reason="template_cluster_downgrade_suppressed_by_ironclad";真围标铁证路径正常生效

#### Scenario: 不受影响维度不调整

- **WHEN** A-B 在同簇,section_similarity PC=70 iron=false / metadata_machine PC=30 iron=false / price_consistency PC=50 iron=false / price_anomaly OA=20 / image_reuse OA=88(本期不写 iron)/ error_consistency OA=40 has_iron_evidence=false
- **THEN** 5 条 PC/OA 的 adjusted_score 均沿用 raw,is_ironclad/has_iron_evidence 沿用 raw;无 adjustment 记录

#### Scenario: 真围标 + 同模板 → text_sim 铁证豁免 + 独立铁证维度保留 → 仍能判 high

- **WHEN** 3 bidder 全在同簇(metadata 污染);text_similarity PC A-B raw=95 is_ironclad=true(LLM plagiarism ≥3 段;模板外仍有大量抄袭);section_similarity PC A-B=85 iron=true(章节内容碰撞);error_consistency OA has_iron_evidence=true
- **THEN** text_sim 降权豁免保留 95 + iron=true;section_similarity 不受影响保留 85 + iron=true;error_consistency 不受影响保留 has_iron_evidence=true;`has_ironclad=True`(多维铁证);`formula_total≥85`;`risk_level=high`;真围标铁证链完整保留,模板排除不掩盖真信号

#### Scenario: adjustment 不回写 DB

- **WHEN** adjustment 对 PC A-B.structure_similarity 产出 adjusted_score=0
- **THEN** DB 中 `pair_comparisons` 行的 `score` 字段保持原值 100(agent 写入值);`analysis_report.template_cluster_adjusted_scores.adjustments` JSONB 记录 raw=100 adjusted=0;重跑 judge 读 DB 原值后再次应用 adjustment,结果幂等

#### Scenario: template_cluster_detected 仅在有真实簇时 true

- **WHEN** 模板簇识别返回非空 cluster 列表且产生 ≥1 条 adjustment
- **THEN** `AnalysisReport.template_cluster_detected=true`
- **WHEN** 模板簇识别返空 list(所有 bidder metadata 独立或 NULL)
- **THEN** `template_cluster_detected=false` + `template_cluster_adjusted_scores=null`

#### Scenario: 无 cluster 命中走老路径(invariant 3)

- **WHEN** `_detect_template_cluster` 返空 list(metadata 全 NULL 或两两不相交)
- **THEN** 后续 helper 全部传 None;`_has_sufficient_evidence` 走 AgentTask 分母;行为与 change 前完全等价(不引入任何回归)


## MODIFIED Requirements

### Requirement: 证据不足判定规则

系统 SHALL 在调用 L-9 LLM 综合研判**之前**先做"证据不足"前置判定。

证据不足的判定函数签名扩 2 个 keyword-only 可选参数(向后兼容):
```
_has_sufficient_evidence(
    agent_tasks,
    pair_comparisons,
    overall_analyses,
    *,
    adjusted_pcs: AdjustedPCs | None = None,
    adjusted_oas: AdjustedOAs | None = None,
) -> bool
```

`adjusted_pcs is None and adjusted_oas is None`(默认,老调用点行为完全不变)时:
1. **铁证短路**:若当前版本的 `PairComparison` 任一 `is_ironclad=True`,或 `OverallAnalysis` 任一 `evidence_json.has_iron_evidence=True` → 直接判定为**有足够证据**(铁证本身就是最强信号),走原 LLM 路径
2. **信号型 agent 判定**:否则过滤 AgentTask 里 `status='succeeded'` 且 `agent_name in SIGNAL_AGENTS` 的任务作为"有效信号"
   - `SIGNAL_AGENTS = {"text_similarity", "section_similarity", "structure_similarity", "image_reuse", "style", "error_consistency"}` — 这些 agent 的 score=0 表示"真的没算出信号"
   - **不在**该集合内的 agent(`metadata_author / metadata_time / metadata_machine / price_consistency`)**不计入**判定分母
3. 若有效信号为空 **或** 全部 `score` 为 0(或 NULL) → 判定为**证据不足**

任一 adjusted dict 非 None 时(本 change 调用点,无 cluster 命中时仍传 None 走老路径):
1. **铁证短路读 adjusted iron**:遍历 PC,iron 状态读 `adjusted_pcs.get(pc.id, {}).get("is_ironclad", pc.is_ironclad)`(若 `adjusted_pcs is None` 则直读 raw);遍历 OA 同理读 `adjusted_oas.get(oa.id, {}).get("has_iron_evidence", oa.evidence_json.get("has_iron_evidence"))`。被 template adjustment 抑制为 false 的不视为铁证
2. **信号判定分母从 AgentTask 切到 OA**:过滤 `oa.dimension in SIGNAL_AGENTS and adjusted_or_raw_score > 0`(`adjusted_or_raw_score = adjusted_oas.get(oa.id, {}).get("score", oa.score)`);AgentTask 仍保留供 agent 执行层面诊断,**不再作为信号判定分母**
3. **前置条件**:调用方 MUST 确保 `overall_analyses` list 已含全部 11 行(4 global + 7 pair 类 DEF-OA)。`judge.py` DEF-OA 写入步骤 `session.add(oa)` + `flush` 后必须 `overall_analyses.append(oa)` 同步 local list;否则 SIGNAL_AGENTS 中 text/section/structure_similarity 的 OA 在分母中缺席,新分母永远 False 误判 indeterminate

**helper 级 kwarg 联动**(具体改造手法见 design D5):`_compute_dims_and_iron` / `_has_sufficient_evidence` / `summarize`(经 `_run_l9` 透传)同步加 `adjusted_pcs / adjusted_oas` kwarg(默认 None 时行为完全不变);`_compute_formula_total` 不扩 kwarg(只读 per_dim_max + has_ironclad);`compute_report` 自身签名/语义不变。

若返 False → 跳过 LLM 调用,直接设 `AnalysisReport.risk_level='indeterminate'` + `llm_conclusion="证据不足,无法判定围标风险(有效信号维度全部为零)"`,`total_score` 按公式照算
若返 True → 进入原 L-9 LLM 调用路径

#### Scenario: 信号型 agent 全零 → 证据不足(老调用点 / adjusted_scores=None)

- **WHEN** 无铁证,11 个 AgentTask 中 3 个 skipped、8 个 succeeded 但信号型 agent 得分全为 0;`adjusted_pcs=None / adjusted_oas=None`
- **THEN** `_has_sufficient_evidence` 返 False;跳过 `call_llm_judge`;AnalysisReport `risk_level='indeterminate'`、`llm_conclusion` 含"证据不足,无法判定"

#### Scenario: 只有 metadata_* 非零信号 → 仍证据不足(老路径)

- **WHEN** 无铁证,`metadata_author.score=50`,但信号型 agent 都是 0 或 skipped;`adjusted_pcs=None / adjusted_oas=None`
- **THEN** `_has_sufficient_evidence` 返 False(metadata_* 不在 SIGNAL_AGENTS 分母里);走 indeterminate 分支

#### Scenario: 铁证短路 → 强制走 LLM 路径(老路径)

- **WHEN** 任一 PC.is_ironclad=True,但所有 AgentTask 的 score=0;`adjusted_pcs=None / adjusted_oas=None`
- **THEN** `_has_sufficient_evidence` 返 True(铁证短路);走原 LLM + 铁证升级路径

#### Scenario: 无 succeeded agent(老路径)

- **WHEN** 所有 AgentTask 都 skipped / failed / timeout,无任何 succeeded,且无铁证;`adjusted_pcs=None / adjusted_oas=None`
- **THEN** `_has_sufficient_evidence` 返 False;同 indeterminate 分支

#### Scenario: 有信号型非零信号照旧走 LLM(老路径)

- **WHEN** 有效信号 agent 至少一个 score > 0;`adjusted_pcs=None / adjusted_oas=None`
- **THEN** `_has_sufficient_evidence` 返 True;正常进入 L-9 LLM 调用

#### Scenario: LLM 失败兜底时仍保持 indeterminate 语义

- **WHEN** 证据不足判定为 False 且 LLM 被跳过,fallback_conclusion 被调
- **THEN** fallback_conclusion 仍按 `risk_level=indeterminate` 处理;`llm_conclusion` 保持"证据不足"语义,不回退到"无围标迹象"文案

#### Scenario: adjusted dict 传入,iron 被抑制 → 铁证短路不命中(新路径)

- **WHEN** `adjusted_pcs` 传入 dict,其中 metadata_author PC 的 is_ironclad 被抑制为 false;原 PC.is_ironclad=true 保留在 DB;无其他真实铁证;`adjusted_oas` 同时传(可只覆盖被剔 OA)
- **THEN** 铁证短路读 `adjusted_pcs[pc.id]["is_ironclad"]=false`,不命中;继续走 OA signal 分母判定

#### Scenario: adjusted dict 传入,OA signal 全零 → indeterminate(新路径)

- **WHEN** adjusted dict 传入,SIGNAL_AGENTS 中所有维度 OA(text_similarity / section_similarity / structure_similarity / image_reuse / style / error_consistency)的调整后 score 全为 0;`overall_analyses` list 长度=11
- **THEN** `_has_sufficient_evidence` 返 False;走 indeterminate 分支

#### Scenario: adjusted dict 传入,text_sim 降权后非零 → 走 LLM(新路径)

- **WHEN** adjusted dict 传入,text_similarity DEF-OA score 调整为 45.5(从 raw 91 降权后),其他 SIGNAL OA=0;无铁证;`overall_analyses` list 长度=11
- **THEN** `_has_sufficient_evidence` 返 True(any 非零);走 LLM 路径;LLM `summarize` 也消费 adjusted dict 输出基于调整后值的 dimensions(防 LLM 拿污染 raw 值后 clamp 拉回污染分);LLM clamp 后最终 risk_level 取决于 LLM 输出(典型 low)

#### Scenario: 真铁证(image_reuse 例外:OA 不写 iron;改用 error_consistency)→ 铁证短路命中

- **WHEN** adjusted dict 传入,error_consistency OA `evidence_json.has_iron_evidence=true` 未被抑制(error_consistency 不在剔除白名单)
- **THEN** 铁证短路命中;返 True 走 LLM + 铁证升级路径;真围标信号在 template 排除下保留有效

#### Scenario: DEF-OA list 长度前置条件失守 → L1 测试断言失败

- **WHEN** 调用方未正确同步 DEF-OA 到 `overall_analyses` local list,调用时 list 长度 < 11
- **THEN** L1 单元测试 MUST 显式断言失败;此前置条件违反不应在生产路径出现

#### Scenario: prod fixture 单 section 信号非零 → 走 LLM(round 4 reviewer M3 边界裁定)

- **WHEN** adjusted dict 传入,reflect prod 真实场景:text_similarity DEF-OA score 调整为 45.80(降权后)/ structure_similarity DEF-OA=0(剔除)/ style OA=0(剔除全覆盖)/ metadata_author / metadata_time DEF-OA=0(剔除)/ section_similarity OA score=70(未受影响,假设 prod 真实分数)/ image_reuse OA=0 / error_consistency OA=0;无铁证(全被抑制 + 无独立 image_reuse/error_consistency 铁证)
- **THEN** `_has_sufficient_evidence` 返 True(text_sim DEF-OA 与 section_sim 各自非零,任一即足);走 LLM 路径;LLM `summarize` 消费 adjusted dict 输出 dimensions(structure/style/metadata_author 全 0);final_total 由 LLM clamp + adjusted has_ironclad=False 决定,典型落 low

