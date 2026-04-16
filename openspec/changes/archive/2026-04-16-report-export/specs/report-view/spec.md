## ADDED Requirements

### Requirement: 报告总览只读视图

系统 SHALL 提供 `GET /api/projects/{project_id}/reports/{version}` 端点(扩展 C6 既有实现),返回 AnalysisReport 总览数据:`{version, total_score, risk_level, llm_conclusion, created_at, dimensions[], manual_review_status, manual_review_comment, reviewer_id, reviewed_at}`(manual_review_* 字段本 change 新增,nullable)。权限:reviewer 仅自己项目 / admin 任意,否则 404 不泄露存在性。

#### Scenario: owner 获取自己项目报告
- **WHEN** reviewer A 请求自己项目的报告
- **THEN** 200 + 上述字段全集;`llm_conclusion` 若以 `"AI 综合研判暂不可用"` 开头,前端渲染黄色降级 banner

#### Scenario: reviewer 获取他人项目报告
- **WHEN** reviewer A 请求 B 的项目报告
- **THEN** 404,不泄露报告存在

#### Scenario: admin 获取任意报告
- **WHEN** admin 请求任一报告
- **THEN** 200

#### Scenario: 未复核报告返回 null
- **WHEN** 报告未被人工复核
- **THEN** 响应中 manual_review_status / comment / reviewer_id / reviewed_at 均为 null

---

### Requirement: 11 维度明细视图

系统 SHALL 提供 `GET /api/projects/{project_id}/reports/{version}/dimensions` 端点,返回 11 维度聚合明细。每维度行:`{dimension, best_score, is_ironclad, evidence_summary, manual_review_json}`,其中:
- `best_score`:该 project+version 下 OA(同维度).score 与 PC(同维度).score 的最大值(聚合自 C6~C13 产出)
- `is_ironclad`:该维度 PC 行中任一 `is_ironclad=true` 即为 true
- `evidence_summary`:从 OA.evidence_json 和 PC.summary 抽取的摘要字符串(不做复杂 transform)
- `manual_review_json`:OA(同维度).manual_review_json(本 change 新增字段)

顺序 MUST 固定为 detect-framework DIMENSION_WEIGHTS 定义的维度顺序。

#### Scenario: 获取维度明细
- **WHEN** 请求 dimensions 端点
- **THEN** 200 + 11 行;顺序与 DIMENSION_WEIGHTS 一致;best_score 聚合自 OA+PC

#### Scenario: 铁证维度标识
- **WHEN** 某维度有 PC 行 is_ironclad=true
- **THEN** 该维度返回 is_ironclad=true

#### Scenario: 维度级复核标记存在时一并返回
- **WHEN** 某维度已被人工复核(OA.manual_review_json 非空)
- **THEN** 该行 manual_review_json 返回 `{action, comment, reviewer_id, at}`

---

### Requirement: pair 对比入口视图

系统 SHALL 提供 `GET /api/projects/{project_id}/reports/{version}/pairs` 端点,返回该 report 所有 PairComparison 行摘要:`{id, dimension, bidder_a_id, bidder_b_id, score, is_ironclad, summary}`。支持 query param `?sort=score_desc&limit=50`,默认按 score 降序。

#### Scenario: 获取 pair 列表
- **WHEN** 请求 pairs 端点
- **THEN** 200 + pair 数组(pair 行按 project_id+version 过滤)

#### Scenario: 按 score 降序排序
- **WHEN** 请求 pairs?sort=score_desc
- **THEN** 响应按 score 降序;is_ironclad=true 的行可通过字段识别

#### Scenario: limit 生效
- **WHEN** 请求 pairs?limit=10
- **THEN** 最多返回 10 行

---

### Requirement: 检测+操作日志合并视图

系统 SHALL 提供 `GET /api/projects/{project_id}/reports/{version}/logs` 端点,合并返回 `AgentTask`(按 project_id+version 过滤,检测执行日志)+ `AuditLog`(按 project_id + report_id 过滤,人工操作日志)按 created_at 倒序的混合流。每条:`{source: 'agent_task' | 'audit_log', created_at, payload}`。支持 `?source=agent_task|audit_log|all`(默认 all),`?limit=100`。

#### Scenario: 合并获取两类日志
- **WHEN** 请求 logs?source=all
- **THEN** 200 + 按 created_at DESC 合并两类事件,每条带 `source` 标签

#### Scenario: 仅获取操作日志
- **WHEN** 请求 logs?source=audit_log
- **THEN** 只返回 audit_log 条目

#### Scenario: 空操作日志
- **WHEN** 报告刚创建无 audit 事件
- **THEN** 返回仅 agent_task 条目(不报错)

---

### Requirement: 降级 banner 哨兵契约

系统 MUST 保持 `llm_conclusion` 字段降级前缀 `"AI 综合研判暂不可用"` 作为前后端契约(C14 已固定)。后端 judge_llm.fallback_conclusion 输出 MUST 以此前缀开头;前端展示 MUST 通过 `startsWith` 匹配此前缀以决定是否渲染降级 banner。

#### Scenario: L-9 LLM 失败降级
- **WHEN** judge_llm 执行失败,触发 fallback_conclusion
- **THEN** `AR.llm_conclusion` 以 `"AI 综合研判暂不可用"` 开头;前端检测到此前缀渲染黄色 banner

#### Scenario: L-9 LLM 成功
- **WHEN** judge_llm 正常返回 LLM 文本
- **THEN** `AR.llm_conclusion` 不含该前缀;前端不渲染 banner
