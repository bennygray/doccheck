## Why

解析流水线完成后（所有投标人达到终态），`project.status` 停留在 `draft`，用户无法启动检测（API 返回 400:"项目未就绪"）。这是 E2E 验收测试中发现的 P1 阻塞性缺陷（DEF-001），核心业务流程断裂。

## What Changes

- 解析流水线每个 bidder 到达终态后，检查同项目所有 bidder 是否均已终态；若是，自动将 `project.status` 从 `draft`/`parsing` 流转到 `ready`
- 上传文件触发解析时，将 `project.status` 从 `draft` 流转到 `parsing`
- 通过 SSE progress_broker 发送 `project_status_changed` 事件，前端无需轮询即可感知状态变化

## Capabilities

### New Capabilities

- `project-status-sync`: 解析流水线完成时自动同步项目状态（draft → parsing → ready），含竞态保护和 SSE 事件通知

### Modified Capabilities

- `parser-pipeline`: run_pipeline 完成时触发项目状态检查
- `detect-framework`: 启动校验 `_PROJECT_START_ALLOWED` 已包含 `ready`，无需改动，但需确认兼容

## Impact

- **后端代码**: `run_pipeline.py`（增加终态聚合逻辑）、`progress_broker`（增加项目级事件）
- **数据库**: 无 schema 变更，仅 `projects.status` 字段值变化
- **前端**: 可选 — 监听新的 `project_status_changed` SSE 事件以实时刷新（当前前端轮询也可兼容）
- **API**: 无接口变更
