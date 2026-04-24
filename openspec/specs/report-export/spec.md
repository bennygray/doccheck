# report-export Specification

## Requirements

### Requirement: SSE endpoint 支持 query param token 认证
SSE endpoint（`/analysis/events`、`/parse-progress`）SHALL 支持通过 URL query parameter `access_token` 传递 JWT token，作为 `Authorization: Bearer` header 的回退。优先级：Header > Query。

#### Scenario: EventSource 通过 query param 认证成功
- **WHEN** 前端使用 `new EventSource("/api/projects/1/analysis/events?access_token=<valid_jwt>")` 连接
- **THEN** 后端 SHALL 从 query param 提取 token 并正常认证，SSE 连接建立成功

#### Scenario: Header 优先于 query param
- **WHEN** 请求同时携带 `Authorization: Bearer A` header 和 `?access_token=B` query param
- **THEN** 后端 SHALL 使用 header 中的 token A 进行认证

#### Scenario: 无 token 仍返回 401
- **WHEN** 请求既无 header 也无 query param
- **THEN** 后端 SHALL 返回 401

---

### Requirement: ExportButton SSE 订阅携带 token
`ExportButton` 组件 SHALL 在创建 EventSource 时通过 query param `access_token` 传递认证 token，确保导出进度事件可正常接收。

#### Scenario: 导出进度正常接收
- **WHEN** 用户点击"导出 Word"按钮
- **THEN** 前端 SHALL 创建带 `?access_token=` 的 EventSource 连接，接收 `export_progress` 事件并更新按钮状态（进度条 → 已生成/失败）

---

### Requirement: AdminRulesPage input 值兜底
AdminRulesPage 中所有 `<input>` 的 `value` 属性 SHALL 不为 null。当 API 返回的维度阈值字段为 null 时，SHALL 使用空字符串作为默认值。

#### Scenario: null 阈值不触发 React 警告
- **WHEN** 某维度的特有阈值字段从 API 返回为 null
- **THEN** 对应 input 的 value SHALL 为 ""（空字符串），浏览器控制台 SHALL 无 React `value prop on input should not be null` 警告

### Requirement: Word 模板支持 indeterminate 与身份信息缺失降级文案

Word 报告导出模板 SHALL 根据 `AnalysisReport.risk_level` 和项目下 bidder 的 `identity_info_status` 字段产出对应降级文案,而非硬编码"低风险/无围标"等误导性结论。

- **risk_level 分支**(`services/export/templates.py` 或 docxtpl 模板逻辑):
  - `high` / `medium` / `low`:保持现有文案(按 change 前行为)
  - `indeterminate`(honest-detection-results 新增):风险等级文案写"证据不足,无法判定";总体结论段落写 AnalysisReport.llm_conclusion 原文("证据不足,无法判定围标风险(有效信号维度全部为零)");**不**套用"经 N 维度比对均未发现异常"等描述性模板(否则与 indeterminate 语义矛盾)
- **identity_info_status 降级段落**:
  - 当项目下**任一** bidder `identity_info_status='insufficient'` 时,`error_consistency` 维度段落追加一段:"注:本维度在身份信息缺失情况下已降级判定,结论仅供参考。"
  - 若所有 bidder 都 `sufficient`,段落不追加此注

#### Scenario: 证据不足报告导出为 Word

- **WHEN** 导出 `risk_level='indeterminate'` 的报告
- **THEN** 生成的 .docx 首页/结论段落含"证据不足,无法判定";不含"低风险"或"无围标迹象"等误导字眼

#### Scenario: 身份信息缺失的 error_consistency 段落含降级提示

- **WHEN** 导出一个含 `identity_info=NULL` bidder 的项目报告
- **THEN** error_consistency 维度段落末尾含"本维度在身份信息缺失情况下已降级判定"字样

#### Scenario: 完整身份信息的报告不追加降级注

- **WHEN** 所有 bidder 都有完整 identity_info,导出报告
- **THEN** error_consistency 段落不含"已降级判定"字样(保持原内容)

#### Scenario: 历史 low/medium/high 报告导出行为不变

- **WHEN** 导出 change 前已生成的 `risk_level='low'` 报告
- **THEN** 内容与 change 前一致,无回归
