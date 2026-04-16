## 1. 实现

- [x] 1.1 [impl] `run_pipeline.py`：新增 `_safe_try_transition(project_id)` 包装函数（try/except + logger.exception）
- [x] 1.2 [impl] `run_pipeline.py`：6 处 `try_transition_project_ready` 调用替换为 `_safe_try_transition`
- [x] 1.3 [impl] `trigger.py`：`_background_tasks` 集合持有 task 引用 + `_task_done` done callback 异常日志

## 2. 测试

- [x] 2.1 [L1] 单元测试：`_safe_try_transition` 捕获异常并记录日志（mock `try_transition_project_ready` 抛异常）
- [x] 2.2 [L1] 单元测试：`_task_done` callback 在 task 异常时记录 ERROR 日志
- [x] 2.3 [L2] E2E 测试：pipeline 正常完成后 project 状态流转到 ready（回归验证）

## 3. 验收

- [x] 3.1 跑 [L1][L2] 全部测试，全绿 (L1: 792 passed, L2: 249 passed)
