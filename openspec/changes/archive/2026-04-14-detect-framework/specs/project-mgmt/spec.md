## MODIFIED Requirements

### Requirement: 项目详情

系统 SHALL 提供 `GET /api/projects/{id}` 端点,返回单个项目的完整信息。reviewer 请求非自己的项目 MUST 返回 404(不得返回 403,以防止泄露项目存在性)。已软删项目 MUST 返回 404。admin 可访问任何未软删项目。返回体 MUST 包含项目基础字段以及四个**占位/扩展字段**:`bidders: [] / files: [] / progress / analysis`;`progress` 结构见 "为 C4+ 预留的占位字段" Requirement;`analysis` 结构由 **C6** 扩展(C6 前恒为 null):

```json
"analysis": null  // C6 前
// C6 后:
"analysis": {
  "current_version": int | null,  // 最新 AgentTask.version;未启动过检测为 null
  "project_status": "draft|parsing|ready|analyzing|completed",
  "started_at": iso8601 | null,  // 最新一轮 MIN(started_at) 或 AgentTask.created_at
  "agent_task_count": int,  // 最新 version 下 AgentTask 总数(未启动为 0)
  "latest_report": {                 // 若 AnalysisReport 行存在
    "version": int,
    "total_score": float,
    "risk_level": "high|medium|low",
    "created_at": iso8601
  } | null
}
```

#### Scenario: reviewer 查看自己的项目

- **WHEN** reviewer A 请求 `GET /api/projects/{id}`,该 id 属于 A
- **THEN** 响应 200,返回体含完整基础字段 + `bidders:[] / files:[] / progress / analysis`

#### Scenario: reviewer 查看他人项目返回 404

- **WHEN** reviewer A 请求 `GET /api/projects/{id}`,该 id 属于 B
- **THEN** 响应 404

#### Scenario: admin 查看任意项目

- **WHEN** admin 请求 `GET /api/projects/{id}`,id 属于任意 reviewer
- **THEN** 响应 200

#### Scenario: 已软删项目返回 404

- **WHEN** 请求已软删项目的详情
- **THEN** 响应 404

#### Scenario: 不存在 id 返回 404

- **WHEN** 请求不存在的 id
- **THEN** 响应 404

#### Scenario: C6 前 analysis 字段为 null

- **WHEN** 项目从未启动过检测(agent_tasks 无对应行)
- **THEN** 响应 `analysis: null`

#### Scenario: C6 后 analysis 字段含 current_version 与 latest_report

- **WHEN** 项目已完成一轮检测(AnalysisReport version=1 存在)
- **THEN** 响应 `analysis.current_version=1, analysis.project_status='completed', analysis.latest_report.total_score` 非 null

---

### Requirement: 为 C4+ 预留的占位字段

项目详情响应 MUST 包含 `bidders / files / progress / analysis` 四个字段。C5 起扩展 `progress` 字段的结构以覆盖解析流水线的阶段计数;**C6 起** `analysis` 字段由 null 扩展为对象(见 "项目详情" Requirement):

- `bidders` 字段返回真实投标人摘要列表(每项含 `id / name / parse_status / file_count`),来自 `bidders` 表的未软删记录(C4 语义保持)
- `files` 字段返回该项目下所有投标人的 `bid_documents` 扁平列表摘要(每项含 `id / bidder_id / file_name / file_type / parse_status / file_role / role_confidence`);**`file_role / role_confidence` 为 C5 新增字段**(C4 阶段恒 NULL,C5 由 LLM 填充)
- `progress` 字段返回项目级汇总,**C5 扩展为**:
  ```json
  {
    "total_bidders": int,
    "pending_count": int,
    "extracting_count": int,
    "extracted_count": int,
    "identifying_count": int,
    "identified_count": int,
    "pricing_count": int,
    "priced_count": int,
    "failed_count": int,
    "needs_password_count": int,
    "partial_count": int
  }
  ```
  `failed_count` 聚合所有失败态(`failed / identify_failed / price_failed`);`partial_count` 聚合 `partial / price_partial`。项目无投标人时所有计数为 0。
- `analysis` 字段返回项目检测汇总,**C6 扩展为** `null | {current_version, project_status, started_at, agent_task_count, latest_report}`(见 "项目详情" Requirement)

**列表响应** `GET /api/projects/`:C6 起 `risk_level` 字段从恒 null → 改为优先取 AnalysisReport.risk_level(最新 version);无 AnalysisReport 行 → 保持 null。

#### Scenario: C5 progress 扩展字段存在

- **WHEN** GET 项目详情,该项目在 C5 解析后
- **THEN** response.progress 为 11 字段 JSON(non-null);所有字段值为 ≥0 整数

#### Scenario: C6 analysis 字段扩展(未检测)

- **WHEN** GET 项目详情,该项目在 C6 起但未启动过检测
- **THEN** response.analysis = null

#### Scenario: C6 analysis 字段扩展(已检测)

- **WHEN** GET 项目详情,该项目已完成一轮检测
- **THEN** response.analysis 为对象;analysis.latest_report 非 null

#### Scenario: 列表 risk_level 取自 AnalysisReport

- **WHEN** GET 项目列表,项目 P1 已完成一轮 risk_level=high 的检测
- **THEN** 列表响应中 P1 的 risk_level='high'(非 null)

#### Scenario: 列表 risk_level 未检测仍 null

- **WHEN** GET 项目列表,项目 P2 从未检测
- **THEN** P2 risk_level=null
