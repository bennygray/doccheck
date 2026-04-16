## Why

L3 验收测试（acceptance-pipeline.spec.ts）发现 3 个缺陷导致通过率仅 72.7%。BUG-2 和 BUG-3 是功能性问题，阻碍文本对比和报告导出两个核心交付能力；WARN-1 是前端代码质量问题。详见 `docs/l3-acceptance-test-report.md`。

## What Changes

- **BUG-2 文本相似度阈值过高**: `TEXT_SIM_MIN_DOC_CHARS` 从 500 降至 300，避免短文档被 preflight skip 导致文本对比页面无数据
- **BUG-3 导出 SSE 认证失败**: `ExportButton` 使用 `EventSource` 连接需认证的 SSE endpoint，但 EventSource API 无法设置 Authorization header。改为 URL query param 传 token 或改用 fetch-based SSE
- **WARN-1 input value null**: `AdminRulesPage` 中维度特有阈值字段值为 null 时触发 React 警告，改为 `?? ""` 兜底

## Capabilities

### New Capabilities

（无新增）

### Modified Capabilities

- `compare-view`: 文本对比的前置条件变更（MIN_DOC_CHARS 500→300），更多短文档可进入对比
- `report-export`: 导出进度 SSE 订阅方式变更，修复 EventSource 认证问题

## Impact

- **后端**: `backend/app/services/detect/agents/text_sim_impl/config.py`（阈值）、`backend/app/api/routes/analysis.py`（SSE 认证方式）
- **前端**: `frontend/src/components/reports/ExportButton.tsx`（SSE 连接）、`frontend/src/pages/admin/AdminRulesPage.tsx`（null 兜底）
- **无 API 契约变化、无数据库变更、无 breaking change**
