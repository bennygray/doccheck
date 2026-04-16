## 1. BUG-2 文本对比阈值

- [x] 1.1 [impl] 修改 `backend/app/services/detect/agents/text_sim_impl/config.py`：`min_doc_chars()` 默认值和回退值 500 → 300
- [x] 1.2 [impl] 更新注释：`text_similarity.py` 和 `section_similarity.py` 的 preflight 文档字符串中 500 → 300
- [x] 1.3 [L1] 运行 `pytest backend/tests/unit/ -k text_sim`，确认现有单测全绿（46 passed）

## 2. BUG-3 SSE query param 认证

- [x] 2.1 [impl] 修改 `backend/app/api/deps.py`：`get_current_user` 增加 `access_token: str | None = Query(default=None)` 参数，Header 无 token 时回退读 query param
- [x] 2.2 [L1] 新增单测：验证 query param token 认证成功、Header 优先于 query、两者都无返回 401（3 passed）
- [x] 2.3 [impl] 修改 `frontend/src/components/reports/ExportButton.tsx`：SSE URL 追加 `?access_token=` 参数
- [x] 2.4 [impl] 修改 `frontend/src/hooks/useDetectProgress.ts`：SSE URL 追加 `?access_token=` 参数
- [x] 2.5 [L2] 运行 `pytest backend/tests/e2e/ -k "sse or export"`，确认现有 L2 全绿（17 passed）

## 3. WARN-1 React input null 兜底

- [x] 3.1 [impl] 修改 `frontend/src/pages/admin/AdminRulesPage.tsx`：维度特有阈值 input `value={v as number}` → `value={(v as number) ?? ""}`
- [x] 3.2 [L1] 运行 `npm test -- --run`（前端 Vitest），确认现有 L1 全绿（92 passed）

## 4. 验证

- [x] 4.1 [L1][L2] 跑全部后端测试 `pytest backend/tests/`，全绿（1044 passed）
- [x] 4.2 [L1] 跑全部前端测试 `npm test -- --run`，全绿（92 passed）
- [x] 4.3 [L3] 跑 `npx playwright test acceptance-pipeline admin-management`，11 passed / 0 failed（含 test 5 对比视图 + test 6 导出）
