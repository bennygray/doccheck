## Context

L3 验收测试发现 3 个缺陷。BUG-1（项目状态流转）已由 DEF-006 修复。本 change 处理剩余的 BUG-2（文本对比阈值）、BUG-3（导出 SSE 认证）、WARN-1（React input null）。

## Goals / Non-Goals

**Goals:**
- BUG-2：降低 TEXT_SIM_MIN_DOC_CHARS 使短文档可进入对比
- BUG-3：修复 EventSource 无法认证 SSE endpoint 的问题
- WARN-1：消除 AdminRulesPage 的 React 控制台警告

**Non-Goals:**
- 不改 SSE 协议或事件格式
- 不改导出 Word 模板渲染逻辑
- 不改检测 agent 算法

## Decisions

### D1: TEXT_SIM_MIN_DOC_CHARS 500 → 300

默认值从 500 降至 300。实际投标文件中短文档（投标函、授权书等）经常不到 500 字，当前阈值导致这些文档被 preflight skip。300 字足以过滤掉空文件和仅含标题的文件，同时允许真实短文档参与对比。

改动点：`backend/app/services/detect/agents/text_sim_impl/config.py` 中 `min_doc_chars()` 默认值和 `ValueError` 回退值。

### D2: SSE endpoint 支持 query param token 认证

**问题**：浏览器 EventSource API 不支持自定义 Header，无法传 `Authorization: Bearer xxx`。当前 `get_current_user` 只从 Header 读 token，导致所有 EventSource SSE 连接认证失败。

**方案**：在 `get_current_user` 依赖中增加 `access_token` query param 回退。优先级：Header Authorization > Query access_token。这是 OAuth2 标准的 bearer token 传递方式之一（RFC 6750 §2.3），也是项目前端 `useParseProgress.ts` 已经在用的模式（只是后端没实现接收端）。

同时修改前端 `ExportButton.tsx` 和 `useDetectProgress.ts`，在 EventSource URL 中追加 `?access_token=` 参数（复用 `useParseProgress.ts` 已有的模式）。

改动点：
- `backend/app/api/deps.py`：`get_current_user` 增加 `access_token: str | None = Query(default=None)` 参数
- `frontend/src/components/reports/ExportButton.tsx`：SSE URL 追加 token
- `frontend/src/hooks/useDetectProgress.ts`：SSE URL 追加 token

### D3: AdminRulesPage input value null → 空字符串

维度特有阈值字段（如 `phash_distance`）从 API 返回可能为 null。React 的 `<input value={null}>` 触发 controlled/uncontrolled 警告。用 `?? ""` 兜底。

改动点：`frontend/src/pages/admin/AdminRulesPage.tsx` 第 220 行 `value={v as number}` → `value={v ?? ""}`。

## Risks / Trade-offs

- **D2 安全性**：query param 中的 token 会出现在服务器访问日志和浏览器历史中。对内部系统可接受；生产环境建议 HTTPS + 日志脱敏。这不是本 change 的范围。
- **D1 假阳性**：降低阈值可能让极短文档（300-500 字）产生低质量的相似度结果。但 preflight 的目的是过滤"无意义"的对比，300 字已足以产生有意义的 TF-IDF 向量。
