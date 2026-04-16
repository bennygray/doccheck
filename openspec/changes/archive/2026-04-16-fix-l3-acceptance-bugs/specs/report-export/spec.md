## ADDED Requirements

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

### Requirement: ExportButton SSE 订阅携带 token
`ExportButton` 组件 SHALL 在创建 EventSource 时通过 query param `access_token` 传递认证 token，确保导出进度事件可正常接收。

#### Scenario: 导出进度正常接收
- **WHEN** 用户点击"导出 Word"按钮
- **THEN** 前端 SHALL 创建带 `?access_token=` 的 EventSource 连接，接收 `export_progress` 事件并更新按钮状态（进度条 → 已生成/失败）

### Requirement: AdminRulesPage input 值兜底
AdminRulesPage 中所有 `<input>` 的 `value` 属性 SHALL 不为 null。当 API 返回的维度阈值字段为 null 时，SHALL 使用空字符串作为默认值。

#### Scenario: null 阈值不触发 React 警告
- **WHEN** 某维度的特有阈值字段从 API 返回为 null
- **THEN** 对应 input 的 value SHALL 为 ""（空字符串），浏览器控制台 SHALL 无 React `value prop on input should not be null` 警告
