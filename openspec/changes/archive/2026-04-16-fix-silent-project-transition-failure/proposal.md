## Why

`run_pipeline` 通过 `asyncio.create_task` 以 fire-and-forget 方式执行，内部 6 处 `try_transition_project_ready` 调用均无异常保护。当该函数因瞬态 DB 错误（连接池耗尽、锁超时等）抛异常时，异常被 asyncio task 静默吞掉，项目状态永远卡在 draft/parsing。手动 `await run_pipeline` 无此问题（异常可见），仅 uvicorn 生产环境偶发。

## What Changes

- `run_pipeline.py`：6 处 `try_transition_project_ready` 调用改为带 try/except + ERROR 日志的安全包装
- `trigger.py`：`asyncio.create_task` 增加 task 引用持有 + done callback 异常兜底日志

## Capabilities

### New Capabilities

（无新能力）

### Modified Capabilities

（无需求级变更——问题是已有 `project-status-sync` 和 `parser-pipeline` 规格的实现缺陷，不涉及行为变更）

## Impact

- **代码**：`backend/app/services/parser/pipeline/run_pipeline.py`、`trigger.py`
- **可观测性**：新增 ERROR 级日志，方便排查瞬态失败
- **行为**：pipeline 某 bidder 的状态流转失败不再导致整个 task 崩溃，其余逻辑正常完成
