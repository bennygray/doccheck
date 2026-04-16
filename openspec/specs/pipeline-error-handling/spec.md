## ADDED Requirements

### Requirement: Pipeline task 异常可观测

fire-and-forget 的 pipeline task（`asyncio.create_task`）内发生的未处理异常 SHALL 以 ERROR 级别写入日志，包含完整 traceback。

#### Scenario: try_transition_project_ready 瞬态失败
- **WHEN** `try_transition_project_ready` 因瞬态 DB 错误抛出异常
- **THEN** 异常以 ERROR 级别记录，pipeline 其余逻辑正常完成，bidder 状态不受影响

#### Scenario: pipeline task 未处理异常
- **WHEN** `run_pipeline` 抛出任何未捕获异常导致 task 终止
- **THEN** done callback 以 ERROR 级别记录异常信息和 task 名称
