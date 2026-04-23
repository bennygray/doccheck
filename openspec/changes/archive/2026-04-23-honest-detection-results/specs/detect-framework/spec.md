## ADDED Requirements

### Requirement: 证据不足判定规则

系统 SHALL 在调用 L-9 LLM 综合研判**之前**先做"证据不足"前置判定:

1. **铁证短路**:若当前版本的 `PairComparison` 任一 `is_ironclad=True`,或 `OverallAnalysis` 任一 `evidence_json.has_iron_evidence=True` → 直接判定为**有足够证据**(铁证本身就是最强信号),走原 LLM 路径
2. **信号型 agent 判定**:否则过滤 AgentTask 里 `status='succeeded'` 且 `agent_name in SIGNAL_AGENTS` 的任务作为"有效信号"
   - `SIGNAL_AGENTS = {"text_similarity", "section_similarity", "structure_similarity", "image_reuse", "style", "error_consistency"}` — 这些 agent 的 score=0 表示"真的没算出信号"
   - **不在**该集合内的 agent(`metadata_author / metadata_time / metadata_machine / price_consistency`)**不计入**判定分母 — 这些 agent 的 score=0 表示"查了没发现碰撞/异常",不代表"无信号",否则会误标真实干净项目为 indeterminate
3. 若有效信号为空 **或** 全部 `score` 为 0(或 NULL) → 判定为**证据不足**,跳过 LLM 调用,直接设 `AnalysisReport.risk_level='indeterminate'` + `llm_conclusion="证据不足,无法判定围标风险(有效信号维度全部为零)"`,`total_score` 按公式照算

证据不足的判定函数 `_has_sufficient_evidence(agent_tasks, pair_comparisons, overall_analyses) -> bool` 纯函数,位于 `backend/app/services/detect/judge_llm.py`:
- 返 False → 证据不足 → 触发 indeterminate 分支
- 返 True → 有足够信号 → 进入原 L-9 LLM 调用路径

#### Scenario: 信号型 agent 全零 → 证据不足

- **WHEN** 无铁证,11 个 AgentTask 中 3 个 skipped、8 个 succeeded 但信号型 agent(text_sim / section_sim / structure_sim / image_reuse / style / error_consistency)得分全为 0
- **THEN** `_has_sufficient_evidence` 返 False;跳过 `call_llm_judge`;AnalysisReport `risk_level='indeterminate'`、`llm_conclusion` 含"证据不足,无法判定"

#### Scenario: 只有 metadata_* 非零信号 → 仍证据不足

- **WHEN** 无铁证,`metadata_author.score=50`(发现作者碰撞),但信号型 agent 都是 0 或 skipped
- **THEN** `_has_sufficient_evidence` 返 False(metadata_* 不在 SIGNAL_AGENTS 分母里);走 indeterminate 分支
- **注**:有人可能觉得这个场景"其实有信号";但作者碰撞单独出现通常是巧合,没有相似度类 agent 背书不足以判风险;保持保守判定

#### Scenario: 铁证短路 → 强制走 LLM 路径

- **WHEN** 任一 PC.is_ironclad=True(如图片 MD5 完全一致),但所有 AgentTask 的 score=0(因为 agent 没把铁证写进 score 字段,只写了 is_ironclad)
- **THEN** `_has_sufficient_evidence` 返 True(铁证短路);走原 LLM + 铁证升级路径;final_total ≥ 85、risk_level='high'(不会自相矛盾)

#### Scenario: 无 succeeded agent

- **WHEN** 所有 AgentTask 都 skipped / failed / timeout,无任何 succeeded,且无铁证
- **THEN** `_has_sufficient_evidence` 返 False;同 indeterminate 分支

#### Scenario: 有信号型非零信号照旧走 LLM

- **WHEN** 有效信号 agent 至少一个 score > 0(如 text_sim=24.5)
- **THEN** `_has_sufficient_evidence` 返 True;正常进入 L-9 LLM 调用,风险等级按公式 + LLM 推断(high/medium/low 三档)

#### Scenario: LLM 失败兜底时仍保持 indeterminate 语义

- **WHEN** 证据不足判定为 False 且 LLM 被跳过,fallback_conclusion 被调
- **THEN** fallback_conclusion 仍按 `risk_level=indeterminate` 处理;`llm_conclusion` 保持"证据不足"语义,不回退到"无围标迹象"文案

---

### Requirement: AnalysisReport risk_level 新增 indeterminate 枚举值

`analysis_reports.risk_level` 字段枚举值 MUST 扩展为 4 类:`high / medium / low / indeterminate`。DB 层面字段类型保持 `String(16)` 无变更(当前无 CheckConstraint),仅需在 Pydantic Literal、前端 TypeScript Union、Word 模板、所有按 `risk_level` 分支的渲染点加 `indeterminate` case。

- `indeterminate` 语义:"证据不足,无法判定围标风险"(对应"证据不足判定规则"Requirement 的输出)
- Pydantic schema `AnalysisReportResponse.risk_level: Literal["high", "medium", "low", "indeterminate"]`
- `project.risk_level`(projects 表 cached 字段)同步支持 indeterminate
- 前端 `types/index.ts` 的 `RiskLevel` 和 `ProjectRiskLevel` union 加 `"indeterminate"` 成员
- 历史 high/medium/low 数据 MUST 零影响(纯前向兼容扩展)

#### Scenario: Pydantic schema 验证 indeterminate

- **WHEN** 构造 `AnalysisReportResponse(risk_level="indeterminate", ...)` 
- **THEN** 验证通过,序列化为 JSON 字段值为 `"indeterminate"`

#### Scenario: 历史 low 数据不受影响

- **WHEN** 读取 change 实施前创建的 AnalysisReport(risk_level="low")
- **THEN** Pydantic 反序列化成功,前端正常渲染为绿色"低风险"标签

#### Scenario: Word 导出支持 indeterminate

- **WHEN** 导出 `risk_level=indeterminate` 的报告为 Word
- **THEN** 模板选择对应文案串(不写"低风险",写"证据不足");文档能正常生成

---

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
4. **[新增] 证据不足前置判定**(honest-detection-results):调 `_has_sufficient_evidence(agent_tasks, pair_comparisons, overall_analyses)`(含铁证短路 + SIGNAL_AGENTS 白名单,见"证据不足判定规则"Requirement);若返 False → **跳过步骤 5-7** 的 LLM 调用,直接 `final_total=formula_total`、`final_level='indeterminate'`、`llm_conclusion="证据不足,无法判定围标风险(有效信号维度全部为零)"`,跳到步骤 8
5. 构造 **L-9 LLM 综合研判** 输入(同原步骤 3,编号后移)
6. LLM 调用(同原步骤 4)
7. **clamp 守护**(同原步骤 5)
8. **失败兜底**(同原步骤 6;对 indeterminate 分支不触发因已跳过 LLM)
9. INSERT AnalysisReport(同原步骤 7)
10. UPDATE `project.status = 'completed'` / `project.risk_level`(同原步骤 8,支持 indeterminate)
11. broker publish `report_ready`(同原步骤 9)

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

#### Scenario: 证据不足触发 indeterminate 分支

- **WHEN** 11 个 AgentTask 里 3 个 skipped + 8 个 succeeded 但 score 全零;judge 运行
- **THEN** LLM 不被调用;AnalysisReport.risk_level='indeterminate'、total_score=0、llm_conclusion 含"证据不足,无法判定";project.risk_level='indeterminate'

---

### Requirement: 检测状态快照 API

系统 SHALL 提供 `GET /api/projects/{pid}/analysis/status` 端点,返回项目当前 version(或最近一次失败版本)的 AgentTask 级快照。权限同项目详情(reviewer 仅自己/admin 任意)。

响应:
```json
{
  "version": int | null,
  "project_status": "draft|parsing|ready|analyzing|completed",
  "started_at": iso8601 | null,
  "report_ready": bool,
  "agent_tasks": [
    {"id", "agent_name", "agent_type", "pair_bidder_a_id", "pair_bidder_b_id",
     "status", "started_at", "finished_at", "elapsed_ms", "score", "summary", "error"}
  ]
}
```

- **[新增] `report_ready`**:当且仅当 `(project_id, version)` 在 `analysis_reports` 表有对应行时返 True;用于客户端区分 "agent 终态但 judge 未完成"(`report_ready=false`)vs "完全完成"(`report_ready=true`)。
- `version=null` 的响应中 `report_ready` 固定为 `false`。
- 项目从未启动检测(无 AgentTask)→ 返 `{"version": null, "project_status": <current>, "report_ready": false, "agent_tasks": []}` 200(非 404,便于前端幂等拉取)。

#### Scenario: 检测中查看快照

- **WHEN** 检测进行中 → `GET /api/projects/{pid}/analysis/status`
- **THEN** 响应 200,`agent_tasks` 列表含所有条目,status 混合 `running / pending / succeeded`,`report_ready=false`

#### Scenario: agent 全终态但 judge 未完成

- **WHEN** 所有 AgentTask 进终态但 `analysis_reports` 该 version 行尚未 INSERT
- **THEN** 响应 `report_ready=false`,提示客户端继续轮询

#### Scenario: 检测完全完成

- **WHEN** `analysis_reports` 该 version 行已写入
- **THEN** 响应 `report_ready=true`;客户端可安全拉取 `/reports/{version}`

#### Scenario: report_ready 与 project_status 短暂不一致时以 report_ready 为权威

- **WHEN** judge_and_create_report 已 INSERT AnalysisReport 行但尚未 UPDATE `project.status='completed'`(两步之间 ~几十毫秒窗口)
- **THEN** `/analysis/status` 响应可能出现 `report_ready=true` + `project_status='analyzing'` 组合;前端 MUST 以 `report_ready` 为拉报告的权威判据,不看 project_status(后者下一次轮询会一致)

#### Scenario: 从未检测过返空

- **WHEN** 新建项目(无 AgentTask)→ 查询
- **THEN** 响应 200 + `{"version": null, "project_status": "draft", "report_ready": false, "agent_tasks": []}`

#### Scenario: 非 owner 返 404

- **WHEN** reviewer A 查询 B 的项目 analysis/status
- **THEN** 响应 404
