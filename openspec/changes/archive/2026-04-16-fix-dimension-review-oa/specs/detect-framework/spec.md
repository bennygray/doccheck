## MODIFIED Requirements

### Requirement: 综合研判骨架与评分公式

所有 AgentTask 进终态(succeeded/failed/timeout/skipped)后,系统 MUST 调 `judge.judge_and_create_report(project_id, version)`,按以下流水线产出 `AnalysisReport`:

1. 加载该 version 所有 `PairComparison` + `OverallAnalysis` 行
2. 纯函数 `compute_report(pair_comparisons, overall_analyses) -> (formula_total, formula_level)` 先算公式层结论:
   a. 每维度取跨 pair/global 最高分 `per_dim_max[dim] = max(all scores for dim)`
   b. `formula_total = sum(per_dim_max[dim] * DIMENSION_WEIGHTS[dim] for dim in 11 维度)`,四舍五入 2 位
   c. 铁证升级:任一 `pc.is_ironclad=true` 或任一 `oa.evidence_json["has_iron_evidence"]=true` → `formula_total = max(formula_total, 85.0)`
   d. `formula_level`:formula_total ≥ 70 → `high`;40-69 → `medium`;< 40 → `low`
3. **[新增] 补写 pair 类维度 OA 行**:对 7 个 pair 类维度(text_similarity / section_similarity / structure_similarity / metadata_author / metadata_time / metadata_machine / price_consistency),系统 MUST 在 AnalysisReport INSERT 之前写入 `overall_analyses` 行,每维度一行。OA 行内容:
   - `score` = 该维度的 `per_dim_max[dim]`(已在步骤 2a 计算)
   - `evidence_json` = `{"source": "pair_aggregation", "best_score": <float>, "has_iron_evidence": <bool>, "pair_count": <int>, "ironclad_pair_count": <int>}`
   - 写入 MUST 幂等:若 `(project_id, version, dimension)` 已有 OA 行则跳过
4. 构造 **L-9 LLM 综合研判** 输入(同原步骤 3,编号后移)
5. LLM 调用(同原步骤 4)
6. **clamp 守护**(同原步骤 5)
7. **失败兜底**(同原步骤 6)
8. INSERT AnalysisReport(同原步骤 7)
9. UPDATE `project.status = 'completed'` / `project.risk_level`(同原步骤 8)
10. broker publish `report_ready`(同原步骤 9)

检测完成后,`overall_analyses` 表 MUST 包含该 version 的全部 11 个维度(4 global + 7 pair),使维度级复核 API 对所有维度可用。

`compute_report` 纯函数签名和语义不变。OA 写入在 `judge_and_create_report` 异步函数内完成。

权重 `DIMENSION_WEIGHTS` 合计 = 1.00,本 change 不调整。

#### Scenario: pair 类维度 OA 行写入

- **WHEN** 2 个投标人检测完成,text_similarity agent 写了 1 行 PairComparison(score=60, is_ironclad=false)
- **THEN** judge 阶段写入 text_similarity 的 OA 行:score=60, evidence_json.source="pair_aggregation", evidence_json.has_iron_evidence=false, evidence_json.pair_count=1

#### Scenario: pair 类铁证维度 OA 行写入

- **WHEN** 3 个投标人检测完成,metadata_author agent 写了 3 行 PairComparison(A-B: score=100 ironclad=true, A-C: score=80 ironclad=false, B-C: score=100 ironclad=true)
- **THEN** judge 阶段写入 metadata_author 的 OA 行:score=100, evidence_json.has_iron_evidence=true, evidence_json.pair_count=3, evidence_json.ironclad_pair_count=2

#### Scenario: OA 写入幂等

- **WHEN** judge_and_create_report 被重复调用(如重试)
- **THEN** 第二次调用不重复写入 OA 行;已有 OA 行保持不变

#### Scenario: 检测完成后 OA 行总数

- **WHEN** 任意检测版本完成(不论 agent 成功/失败/跳过)
- **THEN** overall_analyses 表该 version 恰好有 11 行(每维度一行);维度级复核 API 对全部 11 维度返回 200

#### Scenario: LLM 成功升分跨档

- **WHEN** 11 Agent 跑完,formula_total=65(medium)、无铁证;LLM 返回 `{suggested_total: 75, conclusion: "三维度共振...", reasoning: "..."}`
- **THEN** final_total=75,final_level=`high`(跨档);AnalysisReport.llm_conclusion = LLM 返回的 conclusion 文本;project.risk_level='high'

#### Scenario: LLM 试图降铁证分被守护

- **WHEN** formula_total=88(high + 任一 PC.is_ironclad=true),LLM 返回 `{suggested_total: 60, conclusion: "...", reasoning: "..."}`
- **THEN** clamp step1 max(88, 60)=88;step2 铁证守护 max(88, 85)=88;final_total=88,final_level=`high`;LLM 降分完全无效

#### Scenario: LLM 重试全失败走降级兜底

- **WHEN** formula_total=72、level=high、有铁证;`call_llm_judge` 重试 `LLM_JUDGE_MAX_RETRY` 次后仍返回 `(None, None)`
- **THEN** final_total=72,final_level=`high`;`llm_conclusion` 以固定前缀 `"AI 综合研判暂不可用"` 开头,包含公式结论模板(total/level/铁证维度/top 维度)

#### Scenario: LLM 输出 bad JSON 走降级兜底

- **WHEN** LLM 返回无法解析的字符串(如缺 `suggested_total` 字段)
- **THEN** 等价 LLM 失败,走降级分支;final_total=formula_total,llm_conclusion=fallback_conclusion 模板

## ADDED Requirements

### Requirement: global 类 agent early-return 分支 MUST 写 OA 行

error_consistency 和 image_reuse agent 在 early-return 分支(session=None 或 bidders<2 等数据不足场景)MUST 写入 OA 行(score=0, evidence_json 含 skip_reason),与 style agent 现有行为对齐。

所有 4 个 global agent(error_consistency / image_reuse / price_anomaly / style)在任何执行路径(正常/skip/early-return)下 MUST 保证写入恰好一行 OA。

#### Scenario: error_consistency 数据不足仍写 OA

- **WHEN** error_consistency agent 因 bidders < 2 而 skip
- **THEN** overall_analyses 仍有 error_consistency 行:score=0, evidence_json 含 `skip_reason`

#### Scenario: image_reuse session=None 仍写 OA

- **WHEN** image_reuse agent 在无 session 环境运行(如 L1 测试)
- **THEN** 不写 OA(session=None 静默跳过,与 write_overall_analysis_row 现有契约一致)

#### Scenario: image_reuse 有 session 但数据不足

- **WHEN** image_reuse agent 有 session 但无图片数据
- **THEN** overall_analyses 有 image_reuse 行:score=0, evidence_json 含 `skip_reason`
