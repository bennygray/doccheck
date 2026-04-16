## Context

当前解析流水线 `run_pipeline()` 是 per-bidder 协程，完成后仅更新 `bidder.parse_status` 并发送 `bidder_status_changed` SSE 事件，没有任何代码检查"同项目所有 bidder 是否均已终态"来更新 `project.status`。

项目状态流转预期：`draft` → `parsing` → `ready` → `analyzing` → `completed`。当前仅实现了后两步（`analyzing` → `completed`），前两步缺失。

关键文件：
- `backend/app/services/parser/pipeline/run_pipeline.py` — per-bidder 流水线
- `backend/app/services/parser/pipeline/progress_broker.py` — SSE 事件发布
- `backend/app/services/extract/engine.py` — 解压触发入口

## Goals / Non-Goals

**Goals:**
- 上传文件触发解析时，`project.status` 自动从 `draft` → `parsing`
- 所有 bidder 到达终态后，`project.status` 自动从 `parsing`/`draft` → `ready`
- 发送 `project_status_changed` SSE 事件通知前端
- 处理并发竞态（多个 bidder 同时完成）

**Non-Goals:**
- 前端改动（前端可选监听新事件，但本 change 不强制改前端）
- 项目状态回退（如删除 bidder 后从 ready 退回 parsing）
- 新增 API 端点

## Decisions

### D1: 在 `_set_bidder_terminal()` 后触发项目状态聚合

**选择**: 在 `run_pipeline.py` 中 bidder 到达终态后，调用新函数 `_try_transition_project_ready()` 检查是否所有 bidder 均已终态。

**替代方案**:
- 在 SSE broker 中监听事件触发 — 违反单一职责，broker 应只做消息分发
- 后台定时轮询 — 延迟高，资源浪费
- 前端触发 — 不可靠，用户可能不在线

**理由**: 最自然的协调点，pipeline 完成即检查，无额外延迟。

### D2: 用 `SELECT ... FOR UPDATE` 防止并发竞态

**选择**: 聚合检查时对 project 行加行锁，避免两个 bidder 同时完成时重复更新。

**理由**: 项目级操作频率低，行锁粒度足够小，不会造成性能瓶颈。

### D3: `draft` → `parsing` 在上传触发解析时设置

**选择**: 在 `extract_archive()` 入口处，若 `project.status == 'draft'`，原子更新为 `parsing`。

**理由**: 上传是解析的起点，在此设置最准确。用 `WHERE status='draft'` 条件更新避免重复。

## Risks / Trade-offs

- **[竞态] 多 bidder 同时完成** → `SELECT ... FOR UPDATE` 行锁保护，仅一个协程执行更新
- **[边界] 只有 1 个 bidder 的项目** → 该 bidder 终态即触发 ready，逻辑一致
- **[边界] bidder 解析失败** → 失败也是终态（`identify_failed` / `price_failed`），同样参与聚合
- **[向后兼容] 已有 draft 项目** → 不影响；仅新解析完成时触发状态检查
