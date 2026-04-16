## Context

`trigger_pipeline` 用 `asyncio.create_task(run_pipeline(bidder_id))` 启动 pipeline，属于 fire-and-forget 模式。`run_pipeline` 内部 6 处调用 `try_transition_project_ready` 均无 try/except 保护。该函数内部使用 `SELECT ... FOR UPDATE` 行锁 + 独立 session，在并发高峰期可能因连接池耗尽或锁等待超时抛异常。异常穿透整个 `run_pipeline`，被 asyncio task 静默吞掉。

## Goals / Non-Goals

**Goals:**
- `try_transition_project_ready` 的瞬态失败不再导致整个 pipeline task 崩溃
- 所有 pipeline task 的未处理异常有 ERROR 级日志可观测
- 保持 task 引用防止 GC 回收（asyncio 最佳实践）

**Non-Goals:**
- 不加自动重试（瞬态失败概率低，重试增加复杂度，收益不对等）
- 不改 `try_transition_project_ready` 内部逻辑（FOR UPDATE 锁方案本身没问题）
- 不改 session/连接池配置

## Decisions

### D1: `_safe_try_transition` 包装函数

在 `run_pipeline.py` 新增 `_safe_try_transition(project_id)` 私有函数，内部 try/except + `logger.exception`。6 处调用点全部替换。

**替代方案**: 在 `try_transition_project_ready` 函数内部加 try/except → 不选。该函数本身语义清晰，调用方应该决定如何处理异常；其他调用场景（如手动脚本）可能需要异常传播。

### D2: trigger.py task 引用 + done callback

`_background_tasks: set[asyncio.Task]` 持有引用，`add_done_callback` 注册异常日志回调。task 完成后从集合移除。

**替代方案**: `asyncio.TaskGroup` → 不选。TaskGroup 要求 structured concurrency，与当前 fire-and-forget 场景不匹配，改动范围过大。

## Risks / Trade-offs

- **[Risk] `_safe_try_transition` 吞掉异常后项目状态仍卡住** → 日志可见，运维可手动触发 `try_transition_project_ready`；后续可按需加重试
- **[Risk] `_background_tasks` 集合在极端并发下增长** → pipeline 完成后 done callback 立即移除，不会积压
