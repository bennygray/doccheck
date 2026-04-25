## 1. 数据模型 + migration

- [x] 1.1 [impl] `backend/app/models/analysis_report.py` 加 `template_cluster_detected: Mapped[bool]`(BOOLEAN, nullable=False, default=False, server_default="false") + `template_cluster_adjusted_scores: Mapped[dict | None]`(JSONB, nullable=True)
- [x] 1.2 [impl] alembic `0012_add_template_cluster_fields.py`:upgrade 加两字段(detected DEFAULT FALSE 回填历史行);downgrade 对称 drop;README 加 "prod 一旦消费新字段建议前进修复而非 rollback" 提示
- [x] 1.3 [impl] `backend/app/schemas/analysis_report.py::AnalysisReportResponse` 加 `template_cluster_detected: bool = False` + `template_cluster_adjusted_scores: dict | None = None`

## 2. 模板簇识别 + adjustment 纯函数

- [x] 2.1 [impl] 新文件 `backend/app/services/detect/template_cluster.py`:
  - `TemplateCluster` dataclass(`cluster_key_sample: dict, bidder_ids: list[int]`)
  - `Adjustment` TypedDict(与 spec ADD Req JSONB shape 一致):`scope: Literal["pc","global_oa","def_oa"]`, `pair: list[int] | None`(仅 scope="pc" 时填), `oa_id: int | None`(仅 scope in {"global_oa","def_oa"} 时填), `dimension: str`, `raw_score: float`, `adjusted_score: float`, `raw_is_ironclad: bool | None`(scope="pc" 填 bool,其他填 null), `raw_has_iron_evidence: bool | None`(scope in {"global_oa","def_oa"} 填 bool,scope="pc" 填 null), `reason: Literal["template_cluster_excluded","template_cluster_downgraded","template_cluster_excluded_all_members","template_cluster_downgrade_suppressed_by_ironclad","def_oa_aggregation_after_template_exclusion"]`(5 枚举值)
  - **两 dict**(round 3 H3):`AdjustedPCs = dict[int, dict]`(key=pc.id;value 含 `score: float, is_ironclad: bool, evidence_extras: dict`) + `AdjustedOAs = dict[int, dict]`(key=oa.id;value 含 `score: float, has_iron_evidence: bool, evidence_extras: dict`)
  - `_normalize_created_at(dt: datetime | None) -> str | None`:naive 视 UTC → `astimezone(UTC).replace(microsecond=0).isoformat()`
  - **author 归一化**复用 `app.services.detect.agents.metadata_impl.normalizer.nfkc_casefold_strip`(round 3 reviewer M2),与 metadata_author agent 语义对齐
  - `_detect_template_cluster(bidder_metadata_map: dict[int, list[DocumentMetadata]]) -> list[TemplateCluster]` 纯函数;file_role 过滤由调用方传前完成;union-find 合并等价类
  - `_apply_template_adjustments(pair_comparisons, overall_analyses, clusters) -> tuple[AdjustedPCs, AdjustedOAs, list[Adjustment]]` 纯函数,**不改 ORM 实例**
  - **DEF-OA OA 必须被覆盖**(round 3 reviewer M1):函数对每个剔除/降权维度,产出**两类** adjusted entry:(a) 该维度受污染 PC.id → `adjusted_pcs`(score/is_ironclad);(b) 该维度的 DEF-OA OA.id → `adjusted_oas`(`score = max(adjusted PC scores)` 在该维度内,`has_iron_evidence = any(adjusted PC.is_ironclad)` 在该维度内);否则 helper 读 OA.score 时拿 raw 100 → per_dim_max 仍 100 → 抑制完全失效
  - 常量:`TEMPLATE_FILE_ROLES = frozenset({"technical","construction","bid_letter","company_intro","authorization","pricing","unit_price"})`(与 `parser/llm/role_classifier.py::VALID_ROLES` 对齐,排除 qualification/other)/ `TEMPLATE_EXCLUSION_DIMENSIONS_PAIR = {"structure_similarity", "metadata_author", "metadata_time"}` / `TEMPLATE_DOWNGRADE_DIMENSIONS_PAIR = {"text_similarity"}` / `TEMPLATE_EXCLUSION_DIMENSIONS_GLOBAL = {"style"}` / `TEXT_SIM_DOWNGRADE_FACTOR = 0.5`
- [x] 2.2 [impl] `backend/app/services/detect/judge.py` 辅助函数 `_load_bidder_metadata(session, project_id) -> dict[int, list[DocumentMetadata]]`:**join Bidder where Bidder.project_id == project_id and Bidder.deleted_at.is_(None)**(round 3 reviewer M1 + L1);BidDocument 按 `file_role.in_(TEMPLATE_FILE_ROLES)` 过滤;join DocumentMetadata;缺 metadata 的文档跳过

## 3. judge 流水线 6 步调用顺序改造(helper 级 kwarg + 不回写 DB)

`judge.judge_and_create_report` 严格按以下 6 步执行(round 4 H1+H2 锁:_compute_dims_and_iron 必须**两次调用**才能拆开 raw 写库 / adjusted 算 final 的双消费冲突;DEF-OA OA.id 物理时序前提):

- [x] 3.1 [impl] **step1 load PC + OA**:`judge.py:218-224` 不变(此时 oas 仅含 4 个 global agent 自写的 OA)
- [x] 3.2 [impl] **step2 第一次 `_compute_dims_and_iron(pcs, oas)`**(`judge.py:235`):**不传** adjusted kwarg(默认 None)→ `raw_per_dim_max / raw_has_ironclad / raw_ironclad_dims`,**仅供 step3 DEF-OA 写入复用**(D7 审计要求 raw 入库)
- [x] 3.3 [impl] **step3 DEF-OA 写入 + local list 同步**:`judge.py:243-266` `for dim in PAIR_DIMENSIONS:` 循环体内顺序:`best_score = raw_per_dim_max.get(dim)` + `iron_pcs = [pc for pc in dim_pcs if pc.is_ironclad]` 全 raw → `session.add(oa)` → **`overall_analyses.append(oa)`** 同步 local list(7 次,在循环体内每次 add 后立即 append);`await session.flush()` **在循环外执行一次**;flush 后 7 个 def_oa.id 全部拿到 PK
- [x] 3.4 [impl] **step4 cluster 识别**:调 `_load_bidder_metadata(session, project_id)` → bidder_metadata_map;调 `_detect_template_cluster` → clusters;metadata 查询异常 → 捕获 + ERROR 日志 + clusters=[] 继续
- [x] 3.5 [impl] **step5 adjustment**:`_apply_template_adjustments(pcs, full_11_oas, clusters)` → `(adjusted_pcs, adjusted_oas, adjustments)`;此时 def_oa.id 已存在,可填 DEF-OA OA entry(round 3 reviewer M1 物理时序前提满足)
- [x] 3.6 [impl] **step6a 第二次 `_compute_dims_and_iron(pcs, oas, adjusted_pcs=, adjusted_oas=)`**(`judge.py:266` 之后**新增**调用):`adjusted_per_dim_max / adj_has_ironclad / adj_ironclad_dims`;**仅在 `len(adjustments) > 0` 时执行**;无 cluster 命中则跳过此步,后续 helper 全部传 None,与 change 前完全等价(round 3 reviewer M3)
- [x] 3.7 [impl] **step6b 后续消费 adjusted 版本(formula_total/formula_level 物理位置必须下移 + 子步序顺序锁定)**:
  - **删除 judge.py:238-241 当前位置** 的 `_compute_formula_total(...)` + `_compute_level(...)` 调用(它们当前在 DEF-OA 写入之前,基于 raw_per_dim_max 算出 raw formula_total/formula_level,会被后续 LLM/clamp 路径错误消费)
  - **step6b 子步序锁定**(round 8 reviewer M1)— 必须按以下顺序执行:
    1. 第二次 `_compute_dims_and_iron(pcs, oas, adjusted_pcs=, adjusted_oas=)` → 拿 `adj_per_dim_max / adj_has_ironclad / adj_ironclad_dims`(无 cluster 时传 None,等价 raw 路径)
    2. `_compute_formula_total(adj_per_dim_max, adj_has_ironclad, weights=_weights)` — **必须保留 `weights=_weights` 透传**(round 8 reviewer H2,C17 SystemConfig override 兼容,不可漏带)
    3. `_compute_level(formula_total, risk_levels=_risk_levels)` — **必须保留 `risk_levels=_risk_levels` 透传**(同 C17 兼容)
    4. `_has_sufficient_evidence(agent_tasks, pcs, oas, adjusted_pcs=, adjusted_oas=)` 传双 dict(无 cluster 时传 None)
    5. 分支:**够** → `_run_l9(... per_dim_max, ironclad_dims, ..., adjusted_pcs=, adjusted_oas=)` 透传 + `summarize` 消费 adjusted;`_clamp_with_llm(formula_total, llm_suggested, has_ironclad)` 用第 2 步重算的 formula_total;**不够** → `final_total = formula_total`(第 2 步重算版)+ `final_level = "indeterminate"`
  - **`indeterminate` 分支** `final_total = formula_total` 中的 `formula_total` 必须是新位置(子步序 2)算出的版本(避免取到原位置已删除的 raw formula_total)
- [x] 3.8 [impl] **helper kwarg 扩展**(撤回原 compute_report 签名改造,round 3 H1):
  - `_compute_dims_and_iron(pcs, oas, *, adjusted_pcs=None, adjusted_oas=None)`:循环读 `pc.score / pc.is_ironclad` 优先 `adjusted_pcs.get(pc.id, {}).get(...)`,OA 同理读 `adjusted_oas.get(oa.id, {})`,缺失回落 ORM raw
  - `_compute_formula_total(per_dim_max, has_ironclad, weights=None)` **不扩 kwarg**(仅消费 per_dim_max + has_ironclad,不读 PC/OA;由调用方决定喂 raw 还是 adjusted 版本即可)
  - `_has_sufficient_evidence(at, pcs, oas, *, adjusted_pcs=None, adjusted_oas=None)`:全 None → 老 AgentTask 分母;任一非 None → 铁证短路读 adjusted iron + 信号判定切到 adjusted OA.score
  - `summarize(... *, adjusted_pcs=None, adjusted_oas=None)`(`judge_llm.py`):**改造手法**(round 8 reviewer H1 校正代码事实):
    - `_is_pc_ironclad` (judge_llm.py:211) / `_is_oa_ironclad` (L215) **是** module-level helper,加 `*, adjusted_pcs=None, adjusted_oas=None` kwarg + 内部按 pc.id/oa.id 查 dict 缺失回落 raw;`grep -rn "_is_pc_ironclad\|_is_oa_ironclad"` 全部 caller,summarize 路径透传 adjusted dict
    - `_pc_score` (L281) **是 `summarize` 内的 nested function**,不是 module-level;采用 inline 兜底:summarize 内 `examples.append({...})` 写入点把 `_pc_score(pc)` 替换为 `adjusted_pcs.get(pc.id, {}).get("score", _pc_score(pc))`,**不必把函数提到 module-level**(改动面更小)
    - `fallback_conclusion` (L473) 签名 `(final_total, final_level, per_dim_max, ironclad_dims)` **不消费 PC/OA**,只读 caller 传入的 per_dim_max(已是 adjusted),**无需透传 adjusted dict**
    - 关键防 LLM 拿污染 raw 值输出高 suggested_total → clamp 拉回污染分
  - `_run_l9(... *, adjusted_pcs=None, adjusted_oas=None)` 透传给 summarize
  - **`compute_report` 签名/语义保持不变**(主 spec L268 + L2843 既有契约 + 2 条 L1 signature_unchanged 测试 `test_detect_judge.py:200` / `test_detect_registry.py:149` 不破)
- [x] 3.9 [impl] 构造 `template_cluster_adjusted_scores` JSONB:`{"clusters": [...], "adjustments": [<PC entry 或 DEF-OA OA entry,两类 schema 见 spec ADD Req>...]}`;空 list 时字段写 NULL
- [x] 3.10 [impl] `template_cluster_detected = len(adjustments) > 0`;INSERT AnalysisReport 时写入两字段

## 4. L1 单元测试

- [x] 4.1 [L1] `backend/tests/unit/test_template_cluster_detection.py`:
  - 3 bidder 全同 metadata → 1 cluster bidder_ids=[1,2,3]
  - 2 bidder 同 + 1 独立 → 1 cluster [1,2]
  - bidder 多份文档集合相交判簇(`S_A={(LP,t1),(LP,t2)}, S_B={(LP,t1)} → 同簇`)
  - **author 归一化**(round 3 reviewer M2):全角/半角混排("LP" / "ＬＰ" / " lp ")经 `nfkc_casefold_strip` 归一为同一 cluster_key
  - metadata author=NULL → 该文档跳过 + WARNING(若该 bidder 其他文档有值仍参与)
  - aware vs naive datetime 同瞬间归一化后判同 key
  - 全独立 → 返空
  - 1 bidder → 返空
  - 传递闭包(union-find):A-B 同簇 + B-C 同簇 → 合并为 [A,B,C] 一个 cluster
  - prod fixture metadata `(2023-10-09 07:16:00+08:00)` 经 `_normalize_created_at` 后 strict equality `"2023-10-08T23:16:00+00:00"`
  - **stress** N=20 bidder 全两两不相交 → 返空 list 在 < 100ms(union-find O(N²) 上界验证,first subagent L4)
- [x] 4.2 [L1] `backend/tests/unit/test_template_adjustments.py`:
  - structure pair 两端同簇 + iron=true(round 3 reviewer M3,与 prod 真实形态对齐)→ adjusted_pcs[pc.id]={score:0, is_ironclad:false, evidence_extras 含 raw_score=100/raw_is_ironclad=true};**同时**在 adjusted_oas[def_oa.id] 产 entry={score:0, has_iron_evidence:false}(M1 锁 DEF-OA 覆盖)
  - structure pair 一端同簇一端独立 → 不调整
  - metadata_author PC iron=true → adjusted_pcs[pc.id] iron 抑制 + DEF-OA adjusted_oas iron 抑制
  - metadata_time PC iron=true → 同上抑制 + DEF-OA OA 覆盖
  - style 全 bidder 在簇 → adjusted_oas[style_oa.id] score=0 + reason="template_cluster_excluded_all_members";**注**:style 不写 has_iron_evidence,evidence_extras 不断言 raw_has_iron_evidence
  - style 部分 bidder 在簇(3 家里 2 家)→ 保留原分无 adjustment
  - text_sim pair 两端同簇 无铁证 → adjusted_pcs[pc.id] score = `round(raw * 0.5, 2)` + reason="template_cluster_downgraded";**同时** adjusted_oas[def_oa.id] score=`max(adjusted PC scores)`(降权后的 max)
  - text_sim pair 两端同簇 **有铁证**(模拟 `compute_is_ironclad` ≥3 段 plagiarism judgments dict)→ 保留原分 + adjusted iron=true + reason="template_cluster_downgrade_suppressed_by_ironclad";DEF-OA 同步保留高分
  - **text_sim 3 对 PC 全部 iron=true 全豁免 case**(round 8 reviewer M4):3 bidder 全簇,3 对 text_sim PC raw=95/93/91 全 iron=true → 全部豁免 → adjusted_pcs[pc.id].score=raw / iron=true × 3;**断言** `adjusted_oas[def_oa.id].score == max(raw PC scores) == 95.0` and `has_iron_evidence == True`(DEF-OA 反映"模板外仍有真抄袭"信号)
  - section_similarity / metadata_machine / price_consistency PC + price_anomaly OA + image_reuse OA + error_consistency OA → 全部不调整(6 维不受影响)
  - **adjusted_pcs / adjusted_oas keys 命名空间隔离**:断言 `pc.id=1` 与 `oa.id=1` 重叠时各自落入对应 dict 不串
  - adjustment 不改 ORM 实例(pc.score 在函数前后 `id(pc)` 相同且 pc.score 保持原值)
- [x] 4.3 [L1] `backend/tests/unit/test_has_sufficient_evidence_with_adjustments.py`(扩 `test_judge_insufficient_evidence.py`):
  - **adjusted_pcs/adjusted_oas=None 老路径回归**:走原 AgentTask.score 分母;现有 5 个 scenario 全绿
  - **adjusted dict 传入新路径**:
    - OA signals 全 0 → False(走 indeterminate)
    - OA signals 至少 1 非零 → True
    - adjusted_pcs 抑制原 PC.is_ironclad=true → 铁证短路**不**命中(看 adjusted iron)
    - adjusted_oas 不抑制 error_consistency OA has_iron_evidence=true → 铁证短路命中 → True
  - **DEF-OA list 长度断言**:在 mock judge 流水线场景下,调用 `_has_sufficient_evidence(adjusted_pcs=..., adjusted_oas=...)` 前 `assert len(overall_analyses) == 11`;若长度 < 11 测试失败(round 2 H2 锁契约)
- [x] 4.4 [L1] `backend/tests/unit/test_compute_dims_and_iron_with_adjustments.py`(替代原 compute_report 测试,因签名不动):
  - `_compute_dims_and_iron(pcs, oas, adjusted_pcs=None, adjusted_oas=None)` 默认 None → 与现有行为完全一致(回归保护;断言 `compute_report` 内嵌调用走默认参数)
  - **6 步调用顺序模拟**(round 4 H1):同一组 fixture 跑两次 `_compute_dims_and_iron`:第一次不传 kwarg → raw 版本(用于模拟 DEF-OA 写入复用);第二次传 adjusted 双 dict → adjusted 版本(用于模拟 final_total)。两次返回值不同时存在(raw per_dim_max[structure]=100 / adj=0)
  - 3 家同模板全覆盖:fixture 必须含 7 条 DEF-OA OA 行(text/section/structure_similarity/metadata_author/metadata_time/metadata_machine/price_consistency 各 1 条;DEF-OA score=raw PC max,has_iron_evidence=any raw PC iron);adjusted_pcs/adjusted_oas 同时覆盖 PC 与 DEF-OA OA → 第二次调用 `adj_per_dim_max[structure]=0 / [metadata_author]=0 / [metadata_time]=0 / [style]=0 / [text]=round(91.59*0.5,2)=45.80`;`adj_has_ironclad=False`(全被抑制);formula_total 远低 70
  - 真围标 + 同模板:text_sim PC iron=true(模拟 LLM judgments ≥3 plagiarism)降权豁免保留 + section_similarity PC iron=true 保留 + error_consistency OA has_iron_evidence=true → adj_has_ironclad=True → formula_total≥85
  - **无 cluster 命中**:adjusted_pcs=None / adjusted_oas=None → 第二次调用直接跳过(production 不调);仅 raw 路径生效
  - **C17 兼容回归**(round 8 reviewer H2):`rules_config={"weights":{"structure_similarity":0.30,...},"risk_levels":{"high":80}}` 注入下,验证 cluster 命中 + 未命中**两条路径**`final_total / final_level` 都正确反映自定义 weights/risk_levels override(防 step6b 子步序漏带 kwarg)
- [x] 4.5 [L1] `backend/tests/unit/test_summarize_with_adjustments.py`(round 3 reviewer H1):
  - `summarize(adjusted_pcs=None, adjusted_oas=None)` 默认 None → LLM dimensions 与现有行为完全一致
  - adjusted dict 传入:`_pc_score` / `_is_pc_ironclad` / `_is_oa_ironclad` 优先读 adjusted;LLM dimensions 中受污染维度的 max_score / iron_count 全归零;断言 LLM 不会被污染 raw 值喂高 suggested_total

## 5. L2 API E2E 测试

- [x] 5.1 [L2] `backend/tests/e2e/test_template_cluster_exclusion.py`:fixture 构造 3 bidder 的 DocumentMetadata 均 `author="LP" + doc_created_at="2023-10-09 07:16:00+08:00"`(file_role=technical);mock agent 产出受污染高分(structure=100 **iron=true** / metadata_author=100 iron=true / metadata_time=100 iron=true / style OA=76.5 / text=91.59 iron=false);跑 judge → AnalysisReport 断言:
  - `template_cluster_detected=true`
  - `adjusted_scores.clusters[0].bidder_ids=[A,B,C]`
  - adjustments 数组 17 条,按 `scope` 字段区分(spec ADD Req 定义):
    - `scope="pc"` × 12:structure×3 + metadata_author×3 + metadata_time×3 + text×3(各 entry 含 `pair / dimension / raw_score / adjusted_score / raw_is_ironclad / reason`)
    - `scope="global_oa"` × 1:style(`pair=null / oa_id=<style_oa.id> / dimension="style" / reason="template_cluster_excluded_all_members"`)
    - `scope="def_oa"` × 4:structure / metadata_author / metadata_time / text 各 1(`oa_id=<def_oa.id> / dimension / raw_score / adjusted_score / raw_has_iron_evidence / reason="def_oa_aggregation_after_template_exclusion"`)
  - DB 中 `OverallAnalysis(dimension="structure_similarity").score=Decimal("100.00")`(raw 写库,符合 D7 审计原则,**不**等于 adjusted=0);其他被剔维度 OA score 同样 raw 入库
  - `risk_level == "low"` **严格断言**(round 4 reviewer M4):text_sim DEF-OA adjusted=45.80 > 0 → `_has_sufficient_evidence` 必返 True 走 LLM,不进 indeterminate 分支;LLM clamp 不会反向拉回污染分(因 summarize 也消费 adjusted dict 输出受污染维度=0 的 dimensions);最终 final_total ≪ 70 → "low"
  - **LLM mock 约束**(round 7 reviewer M1):L2 fixture MUST mock LLM judge 返回 `llm_suggested ≤ formula_total_adj`(典型 mock 30~40)或 mock LLM 拒答走 fallback_conclusion 路径;否则 LLM mock 默认行为返高分会被 `_clamp_with_llm` 取 max 拉过 70 → high → 断言失败误以为本 change bug
  - DB 中 pair_comparisons/overall_analyses 的 score / is_ironclad / has_iron_evidence 保持 agent 原写入值(不回写)
- [x] 5.2 [L2] file_role 过滤 case(round 3 reviewer M2,从 L1 上移):构造 bidder 含 qualification PDF metadata=(LP, t0)(噪音)+ technical docx metadata=(XYZ, t1);另一 bidder 仅 qualification PDF metadata=(LP, t0);跑 judge → cluster 不命中(qualification 被过滤,不参与识别)+ detected=false;断言 `_load_bidder_metadata` SQL 实际过滤生效
- [x] 5.3 [L2] "真围标 + 同模板" case:mock text_sim 3 对 PC iron=true raw=95/93/91(模拟 LLM judgments ≥3 plagiarism)+ section_similarity PC iron=true raw=85 + error_consistency OA has_iron_evidence=true;跑 judge → `risk_level='high'`(铁证豁免 + 独立信号保留);adjustments 里 text_sim 的 reason="template_cluster_downgrade_suppressed_by_ironclad";**DB 断言**(round 8 reviewer M4)text_similarity DEF-OA OA 行 `score == 95.0`(max raw)+ `evidence_json.has_iron_evidence == true`
- [x] 5.4 [L2] "metadata 全 NULL" 回归 case:bidder metadata 全无 → detected=false + adjusted_scores=null;**helper 调用传 None 走老路径**(与 change 前完全等价,round 3 reviewer M3)
- [x] 5.4b [L2] **indeterminate 专用 fixture**(round 4 reviewer M4):3 bidder 全簇,**所有信号维度 mock 后 adjusted=0**(structure=100 iron=true / metadata_author=100 iron=true / metadata_time=100 iron=true / style=76.5 / **text=0** iron=false / section=0 / image_reuse=0 / error_consistency=0)→ adjusted 后 SIGNAL OA 全零 → `_has_sufficient_evidence` 返 False → 跳过 LLM(本 case 无需 mock LLM 因不调用)→ `risk_level == "indeterminate"` 严格断言;验证 indeterminate 分支真实可达
- [x] 5.5 [L2] 跑 `pytest backend/tests/e2e/ -x` 全绿(281 baseline + 新 4 case)

## 6. 真 LLM golden 验证(3 供应商 zip)

- [x] 6.1 [manual] 跑 3 供应商 golden zip 过完整 pipeline,DB dump `analysis_reports` 行证明:
  - `template_cluster_detected=true`
  - `template_cluster_adjusted_scores.clusters` 含 `{"author":"lp","created_at":"2023-10-08T23:16:00+00:00"}` key(注意 nfkc_casefold_strip 后 author 为小写)+ bidder_ids=[A,B,C]
  - adjustments 数组完整(含 PC + DEF-OA OA 双类条目)
  - `risk_level in ("low", "indeterminate")`(从 CH-1 版 high 降)
  - DB pair_comparisons / overall_analyses 原值保留
- [x] 6.2 [manual] 凭证保存 `e2e/artifacts/detect-template-exclusion-2026-04-25/`:`golden_dump.json`(adjusted_scores 全文 + raw vs adjusted 对照表) + `README.md`(前后对比 + 所有断言点逐条验证)

## 7. spec + handoff 文档联动

- [x] 7.1 [impl] `openspec/specs/detect-framework/spec.md` sync(archive 时自动执行,propose 阶段仅写 delta);archive 前 dry-run 验证 MOD "证据不足判定规则" Req 块替换无并行残留
- [x] 7.2 [impl] `docs/handoff.md` section 2 重写本 session 决策;最近 5 条历史 shift

## 8. 总汇

- [x] 8.1 跑 [L1][L2] 全绿
- [x] 8.2 [L3] 跑 `npm run e2e` 全绿(本 change 后 report total 与对比页 PC 原始分会自相显示矛盾,L3 兜底 UX 缝隙不引入回归);若 flaky → 按 CLAUDE.md flaky 条款降级凭证保存 `e2e/artifacts/`
- [x] 8.3 跑 [L1][L2][L3] 全部测试,全绿
