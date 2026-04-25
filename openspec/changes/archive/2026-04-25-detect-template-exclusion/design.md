## Context

CH-1 归档后真 LLM E2E 验证(project 1917,3 供应商 zip)证明系统现有检测维度对"**招标方下发模板被多家合规复用**"场景雪崩假阳:6 份 DB metadata `author=LP + doc_created_at=2023-10-09 07:16:00` 完全一致,触发 structure=100 / text=57~91 / style=76.5 + metadata_author / metadata_time 铁证升级 → `total≥85 → high`。

工程监理、政府采购、基础建设等多数公开招标项目中,使用招标方下发模板**是合规要求**。

**Q1 产品决策 = A**(metadata 簇识别 + 维度剔除/降权)。**Q2 产品决策 = 删 D 兜底**:现有 `DIMENSION_WEIGHTS` 单维上限 0.12 → 单维 100 分 × 0.12 = 12 分,数学上 D5 "单维 ≥70 维度数 <2" 条件永不触发(无铁证路径下 formula_total 到不了 70);A 方案已覆盖核心场景;未来 A 被绕过(投标方改 metadata)再开 follow-up 加兜底,当前不预判。

## Goals / Non-Goals

**Goals:**
- 基于 DB 现成字段(`document_metadata.author` / `doc_created_at`)识别模板簇,零 LLM / 零 N-gram 算法
- 识别粒度:bidder 的 `file_role in {technical, commercial}` 文档对应的 metadata 集合相交非空 → 判同簇
- 命中簇:`structure_similarity` / `metadata_author` / `metadata_time` / `style(global,全覆盖)` **剔除 score + 抑制 is_ironclad**;`text_similarity` 降权 ×0.5 但**铁证豁免**(PC.is_ironclad=true 时不降权,防真围标抄袭被掩盖)
- `_has_sufficient_evidence` 分母切 `OverallAnalysis.score`(adjustment 原地改过),让调整后的全零信号能真触发 indeterminate
- 可观测性:`AnalysisReport.template_cluster_detected` + `template_cluster_adjusted_scores`(clusters / adjustments 原始 vs 调整对照)
- 3 供应商 golden zip 跑完 `risk_level` 从 high 降到 low 或 indeterminate

**Non-Goals:**
- 不实现 N-gram 公共段精细化剔除(成本高,留 follow-up)
- 不做用户显式上传模板 UI(改流程超 scope)
- 不改前端 UI / 不加 badge 标注(纯后端 change,前端不消费 adjusted_scores JSONB);**对比页继续显示原始 PC 分数**(审计原始信号优先);report 页 total 与对比页 PC 原始分短期内会自相显示矛盾,用户可从 `template_cluster_detected=true` 自查;follow-up 加对比页 badge
- 不改 `DIMENSION_WEIGHTS` 全局权重(保持历史数据兼容)
- 不处理模板跨 project 复用识别(每 project 独立判断)
- 不处理"投标方上传套壳模板"(属 follow-up)
- 不把 file_role 过滤推到 `metadata_*` agent 的 `extract_bidder_metadata`(R10 预存量缺陷,scope 限制,follow-up 处理)
- **跑全套 L3 e2e 作回归网保护**(report 与对比页 UX 缝隙需 L3 兜底)

## Decisions

### D1 cluster key = `(author_norm, doc_created_at_normalized)` 两值都非空才组 key

以 `(nfkc_casefold_strip(author), doc_created_at_utc_truncated_to_second)` 为 cluster key。任一字段 NULL/空 → 该文档不参与簇识别(该 bidder 的其他文档若有值仍参与),并写 WARNING 日志。

**author 归一化(round 4 修正)**:**复用** `app.services.detect.agents.metadata_impl.normalizer.nfkc_casefold_strip`(NFKC 全角→半角 + casefold 大小写归一 + strip 两端空白)。理由:metadata_author agent 自身用 `nfkc_casefold_strip` 判 author 相同 + 写 iron=true,cluster 识别若仅用 `.strip()` 弱归一,在全角/大小写差异下(如 "ＬＰ" vs "LP" / "LP" vs "lp")会出现 agent 判同 + iron=true 但 cluster 不命中 → 抑制失效假阳释放。两侧用同一 normalizer 保证语义对齐。

**doc_created_at 归一化**:`dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()`;`aware vs naive` 的 datetime 先统一 `astimezone(UTC)`(naive 视为 UTC)再比较,防 Python `==` 在 aware/naive 混用时 TypeError / 漏匹配。

**hash_sha256 不参与**:投标方会修改内容导致哈希异动,误识别率高。

### D2 簇判定 = bidder 的 metadata 集合相交非空 → 同簇

每个 bidder 收集 `file_role in {"technical", "construction", "bid_letter", "company_intro", "authorization", "pricing", "unit_price"}` 的全部 BidDocument 对应的 DocumentMetadata,构造 cluster_key 集合 `S_i = {(author, created_at_norm), ...}`(NULL 字段的文档跳过)。两个 bidder `i, j` 满足 `S_i ∩ S_j ≠ ∅` → 判同簇。簇是等价类(传递闭包:A-B 同簇 + B-C 同簇 → A-B-C 同簇,实施用 union-find,N≤20 bidder/project 规模 O(N²) 可接受)。

**≥2 bidder 命中** 的等价类才构成有效簇。1-bidder 单点不成簇。

**Rationale**:
- 避免"primary_bid_document" 虚构概念(R1-H4)。一 bidder 多份文档(技术标/施工方案/投标函/报价表)可能 metadata 各不相同,集合相交语义最宽容且语义清晰
- `file_role` 集合与 `parser/llm/role_classifier.py::VALID_ROLES` 对齐,覆盖 docx 类(technical/construction/bid_letter/company_intro/authorization)+ xlsx 类(pricing/unit_price);**排除** `qualification`(PDF 营业执照等 author 常为"Admin"通用值噪音)+ `other`(无效分类)
- 已知遗留缺陷(R10):`metadata_*` agent 内部 `extract_bidder_metadata` 不按 file_role 过滤,会扫 qualification 等噪音文档产生假阳铁证;这是预存量缺陷,本 change 仅在 cluster 识别面切到 file_role 过滤,未推到 agent 层(scope 限制),follow-up 处理
- xlsx (`pricing` / `unit_price`) 纳入 cluster_key 集合的 rationale:工程监理场景投标方有可能仅复用招标方下发的 xlsx 报价模板而 docx 各自重写 → docx 维度不簇但 xlsx 维度簇命中可识别;若 author/created_at 不一致(投标方填表时 xlsx 被覆盖)则 S 自然不增加交集,不引入误识别

### D3 识别位置 = judge 阶段 adjustment,agent 零改动

在 `judge.judge_and_create_report` 内、PC/OA 加载完成后、第一次 `_compute_dims_and_iron`(供 DEF-OA 写入)与 `_apply_template_adjustments` 调用之间执行 `_detect_template_cluster`(production path 不调 `compute_report`);agent 照常跑产出 PC/OA(值为原始分 + 原始 is_ironclad),adjustment 构造**副本**参与公式计算(不回写 DB,详见 D7)。

**Rationale**:agent 代码 0 改动(9 个 agent);原始分完整保留在 PC/OA 表(审计性好);cluster 识别依赖 metadata 已 persisted,judge 阶段天然具备;LLM token 成本可吸收(CH-3 timeout 已 300s)。

### D4 剔除粒度 + 铁证抑制(R1-H1 / R1-H2 / R2-H2 吸收)

**剔除(score → 0 + is_ironclad 抑制)** 四维:
- `structure_similarity` PC:pair 两端 bidder 同簇 → score=0,`is_ironclad`=false,evidence_json 加 `{template_cluster_excluded: true, raw_is_ironclad: <orig>}`
- `metadata_author` PC:同上(铁证源是模板固有 author=LP,非围标行为,必须抑制 iron)
- `metadata_time` PC:同上(doc_created_at 同值本身就是用来识别模板簇的信号,同一信号不能既识别污染又计分)
- `style` OA(global):**所有** bidder 均在某一簇 → score=0,`evidence_json.has_iron_evidence=false + template_cluster_excluded_all_members=true`;**部分** bidder 在簇 → 保留原分(R2-M5 / 本 change 先期简化,follow-up 挂 R5)

**降权(score × 0.5)** 一维:
- `text_similarity` PC:pair 两端同簇 → `score = raw * 0.5`,evidence_json 加 `{template_cluster_downgraded: true, raw_score: <orig>}`
- **铁证豁免条款(R2-H2 吸收)**:若 PC.is_ironclad=true(`text_sim_impl/aggregator.py::compute_is_ironclad`:LLM 段级判定 plagiarism 段数 ≥3 或 plagiarism 占比 ≥50%,LLM 已主动区分 template 与 plagiarism)→ **不降权保留原分** + evidence_json 加 `template_cluster_downgrade_suppressed_by_ironclad=true`。这是为防"真围标 + 同模板" 复合场景下真抄袭被模板理由掩盖。LLM 主动判 plagiarism 时,豁免依据比 TF-IDF 阈值更可信(LLM 已排除 template 段)
- 降权 factor 暂硬编码 0.5(design 层面文档化为启发式值,不进 env;follow-up N-gram 时改)

**不受影响维度**:`section_similarity` / `metadata_machine` / `price_consistency` / `price_anomaly` / `image_reuse` / `error_consistency`(共 6 维;加上剔除 4 维 + 降权 1 维 = 11 维全覆盖)
- `section_similarity` **不**剔除理由:工程监理 3 家多重新排版章节,golden 未踩到;若未来假阳再开 follow-up 加入(风险见 R9)
- 其他维度语义与模板无关
- 各维度 is_ironclad 写入事实(影响 scenario / fixture 真实性):`metadata_author` / `metadata_time` / `metadata_machine` / `text_similarity`(LLM plagiarism 判定)/ `section_similarity` / `structure_similarity` / `price_consistency` 写 PC.is_ironclad;`error_consistency` 写 OA.evidence_json.has_iron_evidence;**`image_reuse` 与 `style` 本期不写 iron**(参 `image_reuse.py:9` "is_iron_evidence 始终 False" + `style.py::_build_evidence` 不输出 has_iron_evidence)— 涉及这两个 agent 的 fixture 不能假设原 iron=true

### D5 helper 级 kwarg 扩展 + 分母切换(round 2 H3 / round 3 H1+H2 吸收 / round 4 修正)

**round 4 修正**:撤回上一版"`compute_report` 扩签名"决定。原因:`compute_report` 在 production path **不被调用**(`judge.py:235` 直调 `_compute_dims_and_iron` / `_compute_formula_total` / `_compute_level`),且主 spec L268 + L2843 + 2 条 L1 测试(`test_detect_judge.py:200` / `test_detect_registry.py:149`)硬约束 `compute_report` 签名不变。改为 helper 级扩 kwarg。

涉及 helper(全部加 keyword-only `*, adjusted_pcs=None, adjusted_oas=None`,默认 None 时行为完全等价于本 change 前):

1. `_compute_dims_and_iron(pcs, oas, *, adjusted_pcs=None, adjusted_oas=None)`:循环读 `pc.score / pc.is_ironclad / oa.score / oa.evidence_json.has_iron_evidence` 时优先查 adjusted 对应 dict,缺失回落 ORM raw
2. `_compute_formula_total(per_dim_max, has_ironclad, weights=None)` **不扩 kwarg**:其内部不读 PC/OA 任何字段,仅消费 `per_dim_max + has_ironclad`(已在第二次 `_compute_dims_and_iron` 阶段反映 adjusted);由调用方决定喂 raw 还是 adjusted 版本
3. `_has_sufficient_evidence(agent_tasks, pcs, oas, *, adjusted_pcs=None, adjusted_oas=None) -> bool`:
   - `adjusted_pcs is None and adjusted_oas is None`(老调用点) → 走原 AgentTask 分母,行为完全不变
   - 任一非 None → 走新分母:铁证短路读 adjusted iron / has_iron_evidence,信号判定分母从 AgentTask 切到 OA 的 adjusted_or_raw_score
4. `summarize(...)` (LLM 路径,`judge_llm.py:281+`):同步加 kwarg。**代码事实(round 8 reviewer H1 校正)**:
   - `_is_pc_ironclad(pc)`(`judge_llm.py:211`)/ `_is_oa_ironclad(oa)`(L215) **是** module-level helper,被多处调用
   - `_pc_score(pc)` **是 `summarize` 内的 nested function**(L281,在 `if pc_list:` 分支内定义),不是 module-level
   - `fallback_conclusion`(L473)签名 `(final_total, final_level, per_dim_max, ironclad_dims)` **完全不消费 PC/OA**,只读 caller 传入的 per_dim_max(已是 adjusted),无需透传 adjusted dict
   - **改造方式**:
     - `_is_pc_ironclad` / `_is_oa_ironclad` 加 `*, adjusted_pcs=None, adjusted_oas=None` kwarg,内部按 `pc.id` / `oa.id` 查 dict 缺失回落 raw;grep 所有 caller 确保 summarize 路径透传(fallback_conclusion 路径不需要)
     - `_pc_score` 选择 (B):**保持 nested**,在 `summarize` 内 `examples.append({...})` 写入点 inline 处理 `adjusted_pcs.get(pc.id, {}).get("score", _pc_score(pc))` 替换原 `_pc_score(pc)` 调用。改动面更小,不需要把函数提到 module-level
   - **关键**:防 LLM 拿污染 raw 值输出高 suggested_total → `_clamp_with_llm` 取 max → final_total 被拉回污染分

**production path 改造点(round 5 修正:锁 6 步调用顺序)**:

`judge.py:218-325` 当前是单点 `_compute_dims_and_iron(L235)` + DEF-OA 写入 + LLM 三路复用 `per_dim_max`,**这一份计算结果同时被 "DEF-OA 写库(必须 raw 才符合 D7)" 与 "formula_total / final_total / LLM (必须 adjusted)" 两个语义相反的下游消费**。helper 加 kwarg 不能解决单次调用喂哪一份的问题。同时,`_apply_template_adjustments` 需要 DEF-OA OA.id,但 DEF-OA 在 L243-266 才 add+flush 拿到 PK,在 cluster 识别之前不存在。

新调用顺序(production path):
1. **load PC + OA**(L218-224 不变,此时 oas 仅含 4 个 global agent 自写的 OA)
2. **第一次 `_compute_dims_and_iron(raw)`** — 不传 adjusted kwarg(走默认 None),拿 `raw_per_dim_max / raw_has_ironclad / raw_ironclad_dims`,**仅供 DEF-OA 写入复用**
3. **DEF-OA 写入循环** — 复用 raw_per_dim_max(`best_score = raw_per_dim_max.get(dim)` + `iron_pcs = [pc for pc in dim_pcs if pc.is_ironclad]` 全 raw)+ `session.add(oa)` + `session.flush()`(此后 def_oa.id 存在);写入循环里**同步** `overall_analyses.append(oa)`(round 2 H2 锁契约,确保 list 含 11 行)
4. **load bidder metadata + `_detect_template_cluster`** → clusters(若空,跳到步骤 6 helper 全部传 None 走老路径,与 change 前完全等价)
5. **`_apply_template_adjustments(pcs, full_11_oas, clusters)`** → `(adjusted_pcs, adjusted_oas, adjustments)`;此时 def_oa.id 已 flush 拿到,可正确填 `adjusted_oas[def_oa.id]` entry(round 3 reviewer M1 物理时序前提满足)
6. **step6b 子步序锁定**(round 8 reviewer M1):
   1. **第二次** `_compute_dims_and_iron(pcs, oas, adjusted_pcs=, adjusted_oas=)` → `adj_per_dim_max / adj_has_ironclad / adj_ironclad_dims`
   2. `_compute_formula_total(adj_per_dim_max, adj_has_ironclad, weights=_weights)` — **保留 `weights=_weights` 透传**(C17 SystemConfig override 兼容,round 8 reviewer H2)
   3. `_compute_level(formula_total, risk_levels=_risk_levels)` — **保留 `risk_levels=_risk_levels` 透传**(同 C17)
   4. `_has_sufficient_evidence(agent_tasks, pcs, oas, adjusted_pcs=, adjusted_oas=)` 传双 dict
   5. 分支:**够** → `_run_l9(...)` + `summarize` 透传 + `_clamp_with_llm`;**不够** → `final_total = formula_total`(子步序 2 算出的)+ `final_level = "indeterminate"`

调用点 kwarg 透传清单(行号是当前文件状态参考):
- `judge.py:235` 第一次 `_compute_dims_and_iron` — 不传 kwarg(默认 None,raw 计算)
- `judge.py:266` 之后**新增**第二次 `_compute_dims_and_iron` — 传 `adjusted_pcs / adjusted_oas`(adjusted 计算)
- `judge.py:238` `_compute_formula_total` — 改用第二次 adjusted_per_dim_max + adjusted_has_ironclad
- `judge.py:292` `_has_sufficient_evidence` — 传 `adjusted_pcs / adjusted_oas`
- `judge.py:307+` `_run_l9` 透传给 `summarize` — 传 `adjusted_pcs / adjusted_oas`;`per_dim_max / ironclad_dims` 改用 adjusted 版本
- `judge.py:322` `_clamp_with_llm` — 改用 adjusted formula_total + adjusted has_ironclad

**无 cluster 命中时**(adjustments==[]):跳过步骤 6 第二次 `_compute_dims_and_iron`,直接用步骤 2 的 raw 版本走老路径;`_has_sufficient_evidence` / `summarize` / `_run_l9` 全部传 None;与 change 前行为完全等价(round 3 reviewer M3)。

**两 dict 而非单 dict**(round 3 H3 吸收):`PairComparison.id` 与 `OverallAnalysis.id` 都是各自表自增 PK,取值范围必然重叠(常见 pc.id=1 oa.id=1)。单 dict by id 会读到错位条目。改为:
- `AdjustedPCs = dict[int, dict]`(key = pc.id)
- `AdjustedOAs = dict[int, dict]`(key = oa.id)
- value 含 `score / is_ironclad / has_iron_evidence / evidence_extras`(各自适用字段)

**DEF-OA OA 必须被 adjusted 覆盖**(round 3 reviewer M1 + round 4 H2 吸收):
- DEF-OA 写入(步骤 3)用 raw PC 聚合值写库(D7 审计要求)
- 若 `_apply_template_adjustments` 仅产 PC.id entry,**第二次** `_compute_dims_and_iron(adjusted=...)` 读 OA.score 时拿 raw=100 → adjusted per_dim_max 仍 100 → 抑制完全失效
- **`_apply_template_adjustments` 必须为受污染维度的 DEF-OA OA.id 也产 entry**:
  - `score = max(adjusted PC scores)` 在该维度内
  - `has_iron_evidence = any(adjusted PC.is_ironclad)` 在该维度内
- 即 PC.id entry 与 DEF-OA OA.id entry 一并写入对应 dict,L1 测试显式断言两类 keys 都覆盖
- 物理时序前提(round 4 H2):此函数在步骤 5 调用,此时 DEF-OA 已 flush 拿到 PK,def_oa.id 可作 key

**DEF-OA list 同步**(round 2 H2 + round 3 锁契约):步骤 3 在 `session.add(oa)` + `flush` 之后 `overall_analyses.append(oa)` 同步 local list,确保步骤 5 `_apply_template_adjustments` 收到的 oas 含全部 11 行(4 global + 7 pair DEF-OA),且步骤 6 helper 调用时 list 也是 11 行;L1 显式断言。

**Rationale**:adjustment 和证据判定/LLM summary 消费同一信息源,避免语义割裂。helper 级 kwarg 默认 None 保持主 spec 老契约 + L1 signature_unchanged 测试不破。这是对主 spec "证据不足判定规则" Req 的 MOD;`compute_report` 自身签名/语义不变,无需 MOD 主 spec L268 / L2843 契约。

### D6 可观测性字段结构

```json
// analysis_report.template_cluster_adjusted_scores (JSONB, nullable)
{
  "clusters": [
    {
      "cluster_key_sample": {"author": "lp", "created_at": "2023-10-08T23:16:00+00:00"},  // author 经 nfkc_casefold_strip 归一化后为小写
      "bidder_ids": [1, 2, 3]
    }
  ],
  "adjustments": [
    // scope="pc" entries(示例只列 1 对,实际 3 bidder 全簇会有 12 条 PC entry)
    {"scope": "pc", "pair": [1, 2], "oa_id": null, "dimension": "structure_similarity", "raw_score": 100.0, "adjusted_score": 0.0, "raw_is_ironclad": true, "raw_has_iron_evidence": null, "reason": "template_cluster_excluded"},
    {"scope": "pc", "pair": [1, 2], "oa_id": null, "dimension": "metadata_author", "raw_score": 100.0, "adjusted_score": 0.0, "raw_is_ironclad": true, "raw_has_iron_evidence": null, "reason": "template_cluster_excluded"},
    {"scope": "pc", "pair": [1, 2], "oa_id": null, "dimension": "metadata_time", "raw_score": 100.0, "adjusted_score": 0.0, "raw_is_ironclad": true, "raw_has_iron_evidence": null, "reason": "template_cluster_excluded"},
    {"scope": "pc", "pair": [1, 2], "oa_id": null, "dimension": "text_similarity", "raw_score": 91.59, "adjusted_score": 45.80, "raw_is_ironclad": false, "raw_has_iron_evidence": null, "reason": "template_cluster_downgraded"},
    // scope="global_oa" entry(style;raw_is_ironclad 对 style 无意义,统一 null 与 spec L114 对齐)
    {"scope": "global_oa", "pair": null, "oa_id": 7, "dimension": "style", "raw_score": 76.5, "adjusted_score": 0.0, "raw_is_ironclad": null, "raw_has_iron_evidence": false, "reason": "template_cluster_excluded_all_members"},
    // scope="def_oa" entry(受污染维度的 DEF-OA aggregation,oa_id 在 step3 flush 后获得 PK)
    {"scope": "def_oa", "pair": null, "oa_id": 12, "dimension": "structure_similarity", "raw_score": 100.0, "adjusted_score": 0.0, "raw_is_ironclad": null, "raw_has_iron_evidence": true, "reason": "def_oa_aggregation_after_template_exclusion"}
  ]
}
```

**`template_cluster_detected`** = `len(adjustments) > 0`(无 D 兜底后语义单一:有真实簇命中触发了调整)。

`cluster_key_sample` 只存示例(实际 S_i ∩ S_j 可能是集合,存任一命中 key 即可,查证足够)。

### D7 adjustment 不回写 DB(R2-M3 吸收 / round 4 双 dict 修正)

`_apply_template_adjustments` **不原地改 ORM 实例的 score/is_ironclad/evidence_json**,改为:
- 输入:原始 `pair_comparisons: list[PairComparison]` / `overall_analyses: list[OverallAnalysis]` / `clusters: list[TemplateCluster]`
- 输出:`(adjusted_pcs: AdjustedPCs, adjusted_oas: AdjustedOAs, adjustments: list[Adjustment])`
  - `AdjustedPCs = dict[int, dict]`(key = pc.id;避免与 OA PK 冲突)
  - `AdjustedOAs = dict[int, dict]`(key = oa.id)
  - value 含 `score: float, is_ironclad: bool, has_iron_evidence: bool, evidence_extras: dict`(适用字段)
- 受污染维度的 PC.id + DEF-OA OA.id **同时**产 adjusted entry(M1 吸收)
- helper 级消费(D5):`_compute_dims_and_iron` / `_has_sufficient_evidence` / `summarize`(经 `_run_l9` 透传)加 `adjusted_pcs / adjusted_oas` kwarg,优先查 adjusted 缺失回落 raw;**`_compute_formula_total` 不扩 kwarg**(仅消费 per_dim_max + has_ironclad,不读 PC/OA)
- DB 表中 PC/OA 行保留 agent 写入的原始 score + is_ironclad(审计原始信号)
- `analysis_report.template_cluster_adjusted_scores` JSONB 存对照表

**Rationale**:避免 `session.commit` 把 ×0.5 写回 PC 表导致重跑 judge 非幂等;保留 agent 原始信号审计价值;两 dict 命名空间清晰避免 PC/OA PK 错位 silent bug。

### D8 alembic 0012

- `analysis_reports.template_cluster_detected` BOOLEAN NOT NULL DEFAULT FALSE(历史行回填 false)
- `analysis_reports.template_cluster_adjusted_scores` JSONB NULL
- downgrade 对称 drop
- 文档化:prod 一旦消费过该字段再 downgrade 会丢审计数据,README 提示"前进修复优于 rollback"(R2-L2 吸收)

## Risks / Trade-offs

- **[R1 author 被覆盖漏识别]** 投标方主动改文档 author → cluster 不命中 → 走原打分;本 change 无兜底(D 已删)。Mitigation:metadata_author agent 本身会降分;follow-up 若见假阳再开 change 加 B/C 兜底
- **[R2 真围标 + 同模板复合场景]** text_sim ×0.5 可能等比缩小"模板段 + 真抄段"信号。Mitigation:铁证豁免条款(PC.is_ironclad=true 不降权);其他维度(section/metadata_machine/price)仍独立提供真围标信号,不依赖 text 单维
- **[R3 text_sim ×0.5 factor 是启发式]** 无 N-gram diff 则模板占比不可区分。Follow-up:N-gram 精细化
- **[R4 ≥2 阈值误触发]** 两家巧合同 author+created_at → 错误剔除。Mitigation:`template_cluster_adjusted_scores` 可审计;人工复核可发现
- **[R5 style 部分覆盖保留原分]** 部分 bidder 在簇时 style OA 原分已被模板污染但保留。Follow-up:N-gram style 精细化 / 按簇子集重算
- **[R6 存量 report 无 adjusted_scores]** 历史行 detected=false + adjusted=NULL,前端渲染兼容 null(schema Optional,数值展示无感)
- **[R7 agent 白跑成本]** D3 代价;style/text_similarity/error_consistency 的 LLM 调用在簇成员下白花 token,成本可吸收。Follow-up:early-skip
- **[R8 metadata NULL 全面]** 所有 bidder metadata 全 NULL → 返空 list → 走原打分;假阳未治但不引入新 bug
- **[R9 section_similarity 假阳风险]** 工程监理 3 家同章节模板 → section 高分未被剔。本 change 先不纳入;follow-up 见真病例再加
- **[R10 metadata_* agent extractor 不按 file_role 过滤]** `extract_bidder_metadata` 拉 bidder 全部 BidDocument metadata(无 file_role 过滤)。Cluster 识别面切了 file_role,但 metadata_author/time/machine agent 仍扫 qualification(PDF,author 常为"Admin"通用值)产生假阳铁证 → cluster 识别若在 technical 维度返空,无法抑制 qualification 噪音。预存量缺陷,scope 限制本 change 不治;follow-up 把 file_role 过滤推到 agent extractor 层
- **[R10b R10 与 cluster 识别失败的复合风险]** 若 qualification author=Admin 与 真模板 author=LP **在 S 集合上互不相交** 导致 cluster 识别失败,但 metadata_author agent(扫全 file_role 含 qualification)仍可能在 qualification author 命中下写 score=100 + iron=true → adjustment 不触发 → 走铁证升级 ≥85 → high 假阳释放。Mitigation:监控 `template_cluster_detected=false 但 metadata_author iron=true` 的 project 进 follow-up 处理 R10
- **[R11 cluster_key author/created_at 秒级邻近碰撞]** 不同 bidder 模板 created_at 精确到秒但相差 1-2 秒(同批次下发但时钟漂移)→ 漏识别。Mitigation:本 change 严格 truncate-to-second;follow-up 加 "±N 秒容忍" 配置项
- **[R12 image_reuse 未来若改写真 iron 是否纳入剔除白名单]** 当前 image_reuse iron 始终 false 不纳入剔除。未来若改写真 iron(MD5 跨 bidder 碰撞)— 这是真围标信号,理论上**不应**纳入模板簇剔除(图片复用与模板共享是两件事)。follow-up 决策点

## Migration Plan

1. alembic 0012 加 2 字段(历史行 detected=false / adjusted=NULL)
2. 代码部署(engine 不变;judge 加预处理 + 6 步调用顺序改造 + helper 级 kwarg 扩展;`compute_report` 签名/语义不变)
3. 存量 analysis_report 不回填(保留历史结论;前端展示 adjusted=null 无感)
4. 新跑 project 自动走新路径
5. rollback:alembic 0011 + 代码回滚;JSONB 字段删除对新老透明;但**若已消费过新字段,prod 建议前进修复而非 rollback**
