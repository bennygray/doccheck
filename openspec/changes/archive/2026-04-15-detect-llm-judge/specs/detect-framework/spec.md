## MODIFIED Requirements

### Requirement: 综合研判骨架与评分公式

所有 AgentTask 进终态(succeeded/failed/timeout/skipped)后,系统 MUST 调 `judge.judge_and_create_report(project_id, version)`,按以下流水线产出 `AnalysisReport`:

1. 加载该 version 所有 `PairComparison` + `OverallAnalysis` 行
2. 纯函数 `compute_report(pair_comparisons, overall_analyses) -> (formula_total, formula_level)` 先算公式层结论:
   a. 每维度取跨 pair/global 最高分 `per_dim_max[dim] = max(all scores for dim)`
   b. `formula_total = sum(per_dim_max[dim] * DIMENSION_WEIGHTS[dim] for dim in 11 维度)`,四舍五入 2 位
   c. 铁证升级:任一 `pc.is_ironclad=true` 或任一 `oa.evidence_json["has_iron_evidence"]=true` → `formula_total = max(formula_total, 85.0)`
   d. `formula_level`:formula_total ≥ 70 → `high`;40-69 → `medium`;< 40 → `low`
3. 构造 **L-9 LLM 综合研判** 输入:`summary = judge_llm.summarize(pcs, oas, per_dim_max, ironclad_info)`(预聚合结构化摘要,token 稳定 3~8k,见 `L-9 摘要预聚合契约`)
4. 若 `LLM_JUDGE_ENABLED=true` → 调 `judge_llm.call_llm_judge(summary, formula_total)` 产 `(conclusion: str | None, suggested_total: float | None)`(见 `L-9 LLM 调用契约`)
5. **clamp 守护**(见 `L-9 可升不可降 clamp 契约`):
   a. LLM 成功:`final_total = max(formula_total, llm_suggested_total)`
   b. 铁证命中:`final_total = max(final_total, 85.0)`
   c. 天花板:`final_total = min(final_total, 100.0)`
   d. `final_level` 按 `final_total` 重算(可能跨档)
6. **失败兜底**(见 `L-9 LLM 失败兜底模板契约`):LLM 失败 / `LLM_JUDGE_ENABLED=false` / 解析失败 / 超界 → `final_total = formula_total` / `final_level = formula_level` / `llm_conclusion = judge_llm.fallback_conclusion(final_total, final_level, per_dim_max, ironclad_dims)`(前缀标语 + 公式结论模板)
7. INSERT AnalysisReport `{project_id, version, total_score=final_total, risk_level=final_level, llm_conclusion}`
8. UPDATE `project.status = 'completed'` / `project.risk_level = final_level`
9. broker publish `report_ready` 事件

权重 `DIMENSION_WEIGHTS` 合计 = 1.00,C6 占位值由 C12 调整(`price_anomaly` 新增 0.07),本 change **不再调整**(留实战反馈 follow-up)。

`compute_report` 保留作为 **纯函数单一事实源**,契约不变,C6~C13 既有测试全绿。

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

#### Scenario: LLM_JUDGE_ENABLED=false 跳过 LLM

- **WHEN** env `LLM_JUDGE_ENABLED=false`,formula_total=55(medium)
- **THEN** 不调 LLM;final_total=55,final_level=`medium`;llm_conclusion=fallback_conclusion 模板(前缀 "AI 综合研判暂不可用")

#### Scenario: LLM suggested_total 超界走降级

- **WHEN** LLM 返回 `{suggested_total: 120, conclusion: "..."}`(超出 [0,100])
- **THEN** 视为解析失败,走降级分支;final_total=formula_total

#### Scenario: 全 skipped 极端情况仍出报告

- **WHEN** 所有 AgentTask 均 skipped(数据不足),formula_total=0、无铁证
- **THEN** AnalysisReport 生成,final_total=0,final_level=`low`;若 LLM 启用且成功,conclusion 可基于"数据不足"摘要产文;若 LLM 失败,llm_conclusion=fallback_conclusion 模板明示"数据不足"

---

## ADDED Requirements

### Requirement: L-9 摘要预聚合契约

`judge_llm.summarize(pair_comparisons, overall_analyses, per_dim_max, ironclad_info) -> dict` MUST 产生结构化摘要,喂给 L-9 LLM 的 input 必须走本契约,不得直喂 raw `evidence_json`(token 爆炸风险)。

摘要结构 MUST 包含:

```json
{
  "project": {"id": int, "name": str, "bidder_count": int},
  "formula": {"total": float, "level": "high|medium|low", "has_ironclad": bool},
  "dimensions": {
    "<dim_name>": {
      "max_score": float | null,
      "ironclad_count": int,
      "participating_bidders": [str, ...],
      "top_k_examples": [
        {"bidder_a": str, "bidder_b": str, "score": float, "evidence_brief": str}
      ],
      "skip_reason": str | null
    }
  }
}
```

规则:
- `dimensions` 字典 MUST 覆盖 11 维度(全部列出,哪怕 skip)
- `top_k_examples` 截断数由 env `LLM_JUDGE_SUMMARY_TOP_K`(default 3)控制,按 score 倒序
- **铁证 pair/OA 必须无条件列入 top_k_examples**(无论排名),`is_ironclad=true` 或 `evidence.has_iron_evidence=true` 标记
- `evidence_brief`:从 `evidence_json` 抽取关键字段拼接短字符串(≤ 200 字),不直塞整个 JSON
- global 型 Agent(error_consistency / style / image_reuse / price_anomaly):`top_k_examples` 填单行 OA 摘要(bidder_a/b 可为空或填"全局")
- `skip_reason`:`enabled=false` / `preflight failed` / `数据不足` 等,从 evidence_json 的 `skip_reason` 字段透出

token 目标:典型项目(5~10 bidder)摘要 3~8k token,大项目(20+ bidder)≤ 15k token。

#### Scenario: 铁证 pair 无条件入 top_k

- **WHEN** 11 个 pair 分数从高到低,铁证 pair 排第 7 位;top_k=3
- **THEN** 摘要 top_k_examples 列前 3 高分 pair,额外附加第 7 位铁证 pair(共 4 个),铁证标记

#### Scenario: skip 维度仍出现在摘要

- **WHEN** `image_reuse` Agent skip(数据不足),OverallAnalysis.evidence_json 含 `skip_reason`
- **THEN** 摘要 `dimensions.image_reuse` = `{max_score: null, skip_reason: "数据不足", top_k_examples: [], ...}`

#### Scenario: token 体量可控

- **WHEN** 项目 8 bidder × 11 维度 × C(8,2)=28 pair
- **THEN** 摘要 JSON.dumps 后 token 估算 ≤ 8k(非硬性 assert,靠 summary 结构约束)

---

### Requirement: L-9 LLM 调用契约

`judge_llm.call_llm_judge(summary: dict, formula_total: float) -> tuple[str | None, float | None]` MUST 满足以下契约:

- **输入**:`summary`(来自 `summarize`)+ `formula_total`(公式结论,供 LLM 作为"基础分"参考)
- **输出**:`(conclusion, suggested_total)` 成对返回
  - 成功:`(非空 str, 0~100 float)`
  - 失败:`(None, None)` — 调用方统一走降级分支
- **LLM 输出 Schema**(LLM 必须返回如下 JSON):
  ```json
  {
    "suggested_total": float,
    "conclusion": string,
    "reasoning": string
  }
  ```
- **失败判据**(返回 `(None, None)`):
  - 网络/API 错误 → 重试 `LLM_JUDGE_MAX_RETRY` 次,仍失败
  - 超时 `LLM_JUDGE_TIMEOUT_S` 秒 → 重试 / 失败
  - JSON 解析失败(含 `json.JSONDecodeError`)→ 消费重试名额
  - 缺必填字段 `suggested_total` 或 `conclusion` → 消费重试名额
  - `suggested_total` 超界([0, 100])→ 消费重试名额
  - `conclusion` 为空字符串 → 消费重试名额
- **重试策略**:失败后最多重试 `LLM_JUDGE_MAX_RETRY`(default 2)次,即最多调用 3 次;重试间隔 0(贴 C13 style_impl 风格)

#### Scenario: LLM 首次成功

- **WHEN** LLM 首次调用返回合法 JSON `{"suggested_total": 78.0, "conclusion": "三维度共振...", "reasoning": "..."}`
- **THEN** 返回 `("三维度共振...", 78.0)`,不触发重试

#### Scenario: LLM bad JSON 消费重试

- **WHEN** LLM 首次返回 `"not json"`,第二次返回合法 JSON
- **THEN** 第二次成功,返回合法结果;重试计数 +1(首次消费)

#### Scenario: LLM 重试耗尽

- **WHEN** LLM 连续 `MAX_RETRY+1=3` 次返回 bad JSON
- **THEN** 返回 `(None, None)`,调用方走降级

#### Scenario: LLM suggested_total 超界消费重试

- **WHEN** LLM 返回 `{"suggested_total": 120, "conclusion": "..."}`
- **THEN** 视为解析失败,消费重试;若重试耗尽返回 `(None, None)`

#### Scenario: LLM 超时

- **WHEN** LLM 调用超过 `LLM_JUDGE_TIMEOUT_S` 秒无响应
- **THEN** 视为单次调用失败,消费重试

---

### Requirement: L-9 可升不可降 clamp 契约

`judge.judge_and_create_report` MUST 按以下顺序 clamp LLM 建议分数:

1. `final_total = max(formula_total, llm_suggested_total)` — LLM 只能升分,不能降
2. `if has_ironclad: final_total = max(final_total, 85.0)` — 铁证硬下限守护
3. `final_total = min(final_total, 100.0)` — 天花板
4. `final_level = compute_level(final_total)`:≥70 `high` / 40-69 `medium` / <40 `low`

铁证硬下限由 `has_ironclad` 判定,逻辑与 `compute_report` 完全一致:
- 任一 `PairComparison.is_ironclad=true` 或
- 任一 `OverallAnalysis.evidence_json["has_iron_evidence"]=true`

LLM 若试图压低铁证分(建议 suggested_total < 85),clamp 步骤 2 将其无效化。

#### Scenario: LLM 升分跨档

- **WHEN** formula=65(medium)+ 无铁证 + LLM=75
- **THEN** final=75,level=high(跨档)

#### Scenario: LLM 建议低于公式被无效化

- **WHEN** formula=80 + 无铁证 + LLM=70
- **THEN** step1 max(80, 70)=80;final=80

#### Scenario: LLM 试图压铁证分被守护

- **WHEN** formula=88(有铁证)+ LLM=60
- **THEN** step1 max(88,60)=88;step2 铁证 max(88,85)=88;final=88

#### Scenario: LLM 建议与铁证一致

- **WHEN** formula=55 + 有铁证(升到 85)+ LLM=90
- **THEN** formula_total 已 85;step1 max(85, 90)=90;final=90

#### Scenario: 天花板守护

- **WHEN** formula=70 + LLM 意外返回 99.5
- **THEN** final=99.5(合法),不触发天花板

---

### Requirement: L-9 LLM 失败兜底模板契约

`judge_llm.fallback_conclusion(final_total: float, final_level: str, per_dim_max: dict, ironclad_dims: list[str]) -> str` MUST 产一段结构化中文模板字符串,满足:

- **前缀标语**:字符串 MUST 以 `"AI 综合研判暂不可用"` 开头(前端通过前缀 match 识别降级态加 banner)
- **模板内容**(顺序):
  1. 标语:`"AI 综合研判暂不可用,以下为规则公式结论:"`
  2. 总分与等级:`"本项目加权总分 {total} 分,风险等级 {level}。"`
  3. 铁证维度列表(若 `ironclad_dims` 非空):`"铁证维度:{dim1}、{dim2}(共 N 项)。"`;若空:跳过此句
  4. Top 3 高分维度:`"维度最高分:{dim1} {score1}、{dim2} {score2}、{dim3} {score3}。"`(若可用维度 < 3 则全列)
  5. 建议关注(铁证维度优先 + top 高分维度):`"建议关注:{dims}。"`

**约束**:
- 纯函数(无 IO,无副作用)
- 输入为 None / 空 dict 时不抛异常,模板对应字段降级(如 per_dim_max 为空 → 跳过 top3 句)
- `LLM_JUDGE_ENABLED=false` 时等价于 LLM 失败,调用此函数产降级文案

#### Scenario: 正常降级模板

- **WHEN** total=72.5, level="high", per_dim_max={"text_similarity":88, "error_consistency":92, "price_consistency":75, ...}, ironclad_dims=["error_consistency"]
- **THEN** 返回字符串以 `"AI 综合研判暂不可用"` 开头,包含 `"总分 72.5 分"`、`"风险等级 high"`、`"铁证维度:error_consistency"`、`"error_consistency 92"`, `"text_similarity 88"`, `"price_consistency 75"`

#### Scenario: 无铁证模板

- **WHEN** total=55, level="medium", ironclad_dims=[]
- **THEN** 字符串中不含"铁证维度"字样

#### Scenario: 空 per_dim_max 降级

- **WHEN** total=0, level="low", per_dim_max={}
- **THEN** 字符串以标语 + "总分 0 分,风险等级 low。" 结尾,不抛异常

#### Scenario: LLM_JUDGE_ENABLED=false 等价

- **WHEN** env `LLM_JUDGE_ENABLED=false`
- **THEN** judge 跳过 LLM 调用直接调 fallback_conclusion;llm_conclusion 前缀仍为 "AI 综合研判暂不可用"(对用户无感)

---

### Requirement: L-9 环境变量与配置

env 命名空间 `LLM_JUDGE_*`,`judge_llm.load_llm_judge_config() -> LLMJudgeConfig` MUST 读取并校验:

| env | 类型 | default | 语义 |
|---|---|---|---|
| `LLM_JUDGE_ENABLED` | bool | `true` | L-9 总开关;false → 跳过 LLM 直接走降级模板 |
| `LLM_JUDGE_TIMEOUT_S` | int | `30` | 单次 LLM 调用超时秒数 |
| `LLM_JUDGE_MAX_RETRY` | int | `2` | 失败重试次数(0=不重试,最多调用 MAX_RETRY+1 次) |
| `LLM_JUDGE_SUMMARY_TOP_K` | int | `3` | 每维度 top_k_examples 截断数 |
| `LLM_JUDGE_MODEL` | str | `""`(空=LLM 客户端默认) | 指定模型,贴现网 LLM 配置 |

校验规则(宽松风格,贴 C11/C12):
- bool 值非 `"true"/"false"` → fallback default + warn log
- int 非正 或 无法 parse → fallback default + warn log
- `TIMEOUT_S` 范围 `[1, 300]`,超界 fallback default
- `MAX_RETRY` 范围 `[0, 5]`,超界 fallback default
- `SUMMARY_TOP_K` 范围 `[1, 20]`,超界 fallback default

#### Scenario: 默认配置

- **WHEN** 未设任何 `LLM_JUDGE_*` env
- **THEN** config = `(enabled=true, timeout_s=30, max_retry=2, summary_top_k=3, model="")`

#### Scenario: 非法值 fallback

- **WHEN** `LLM_JUDGE_MAX_RETRY=abc` / `LLM_JUDGE_TIMEOUT_S=-1`
- **THEN** 两字段均 fallback 到 default(2 / 30),log warn

#### Scenario: enabled=false 关闭 LLM

- **WHEN** `LLM_JUDGE_ENABLED=false`
- **THEN** `judge_and_create_report` 跳过 LLM 调用,直接走降级分支

---

### Requirement: L-9 LLM mock 扩展

`backend/tests/fixtures/llm_mock.py` MUST 扩 L-9 相关 builder 和 fixture,作为测试单一入口:

- `make_l9_response(suggested_total: float, conclusion: str, reasoning: str = "") -> str` — 构造 L-9 合法 JSON 响应字符串
- `mock_llm_l9_ok(monkeypatch, suggested_total=78.0, conclusion="...")` — patch `call_llm_judge` 返回成功结果
- `mock_llm_l9_upgrade(monkeypatch, formula=65, llm=75)` — 升分跨档场景专用
- `mock_llm_l9_clamped(monkeypatch, formula=88, llm=60)` — LLM 试图降分被守护场景
- `mock_llm_l9_failed(monkeypatch)` — patch 返回 `(None, None)`
- `mock_llm_l9_bad_json(monkeypatch)` — patch LLM 客户端返回 bad JSON(触发解析失败+重试)

**约束**:
- 所有 L-9 测试 MUST 通过 `llm_mock.py` 入口 mock,不得在 test 文件内手写 `monkeypatch.setattr`
- 既有 `test_detect_judge.py` 等 judge 相关 test 默认 patch `call_llm_judge` 返回 `(None, None)`(等价 LLM 失败,走降级分支,total/level 保持公式值,与原断言一致)

#### Scenario: 成功 fixture 可用

- **WHEN** 测试调 `mock_llm_l9_ok(monkeypatch, suggested_total=80, conclusion="...")` + 触发 judge_and_create_report
- **THEN** AnalysisReport.llm_conclusion="...";final_total=max(formula, 80)

#### Scenario: 失败 fixture 走降级

- **WHEN** 测试调 `mock_llm_l9_failed(monkeypatch)` + 触发 judge
- **THEN** llm_conclusion 以"AI 综合研判暂不可用"开头;total=formula_total

#### Scenario: bad json fixture 触发重试

- **WHEN** 测试调 `mock_llm_l9_bad_json(monkeypatch)` + 触发 judge
- **THEN** 内部 LLM 客户端被调用 MAX_RETRY+1 次;最终返回 (None, None) 走降级

---

### Requirement: L-9 judge_and_create_report LLM 集成实施

`backend/app/services/detect/judge.py` 的 `judge_and_create_report(project_id, version)` MUST 集成 L-9 LLM 流水线:

- 现有 `compute_report` 纯函数 **保留不变**,作为"基础分"单一事实源
- 在 `compute_report` 调用后 + INSERT `AnalysisReport` 前,插入 L-9 流水线:
  1. `summary = judge_llm.summarize(...)`
  2. 若 `LLM_JUDGE_ENABLED=true`:`conclusion, suggested = judge_llm.call_llm_judge(summary, formula_total)`
  3. 若 LLM 成功:按 `L-9 可升不可降 clamp 契约` 计算 final_total/final_level;llm_conclusion = conclusion
  4. 若 LLM 失败 / disabled:final_total = formula_total;final_level = formula_level;llm_conclusion = `judge_llm.fallback_conclusion(...)`
- 幂等保证不变:`(project_id, version)` 已有 AnalysisReport → 早返

`judge_llm.py` 模块:
- 单文件 3 函数(`summarize` / `call_llm_judge` / `fallback_conclusion`)
- 不对外 `__all__` 导出(仅 judge.py 内部调用)
- algorithm version 登记:`llm_judge_v1`(记入 `backend/README.md`,不落 DB 字段)

#### Scenario: LLM 成功流水线

- **WHEN** 11 Agent 完成 + LLM mock ok + judge_and_create_report 触发
- **THEN** AnalysisReport 1 行落地;llm_conclusion = LLM conclusion;total/level = clamp 结果

#### Scenario: 幂等跳过

- **WHEN** 同 (project_id, version) 再次调 judge_and_create_report
- **THEN** 检测到已有 AnalysisReport,早返,不调 LLM

#### Scenario: compute_report 纯函数契约不变

- **WHEN** 既有 C6~C13 `test_compute_report_*` 测试运行
- **THEN** 全部通过,无需改动(契约向后兼容)
