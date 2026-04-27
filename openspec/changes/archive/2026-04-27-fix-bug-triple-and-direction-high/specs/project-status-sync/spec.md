## MODIFIED Requirements

### Requirement: 项目状态变更发送 SSE 事件

当 `project.status` 发生变更时,系统 SHALL 通过 progress_broker 发送 `project_status_changed` 事件,payload 包含 `{"new_status": <new>}`。该 Requirement 涵盖 parser 流转 / detect 完成 / detect crash / scanner stuck-recovery 四类路径,所有写库后的 status 变更均 MUST 推该事件。

detect 完成路径 SHALL 在 publish `report_ready` 之前先 publish `project_status_changed`(避免前端"已完成 Tag 显示但报告入口缺失"的 race)。

#### Scenario: 状态流转到 ready 时发送事件
- **WHEN** 所有 bidder 到达终态,`project.status` 从 `parsing` 更新为 `ready`
- **THEN** SSE 事件流发送 `project_status_changed` 事件,payload 包含 `{"new_status": "ready"}`

#### Scenario: 检测完成时发送事件且早于 report_ready
- **WHEN** judge 完成检测,`project.status` 从 `analyzing` 更新为 `completed`
- **THEN** SSE 事件流先发送 `project_status_changed{"new_status": "completed"}`,再发送 `report_ready`;前端任一事件先到都能将状态 Tag 切到"已完成"

#### Scenario: 检测中途异常时回滚状态并发送事件
- **WHEN** detect engine 在 `_execute_agent_task` 通用兜底 except 分支捕获非 AgentSkippedError 异常,`project.status` 从 `analyzing` 回滚为 `ready`
- **THEN** SSE 事件流发送 `project_status_changed{"new_status": "ready"}`,同时发送 `error` event 含 stage 与 message;前端 UI 状态 Tag 切回"待检测"且可见错误提示

#### Scenario: scanner 重启恢复 stuck 任务时发送事件
- **WHEN** scanner 在 lifespan 启动时检测到 stuck 的 agent_task 并将 `project.status` 从 `analyzing` 回滚为 `ready`
- **THEN** SSE 事件流发送 `project_status_changed{"new_status": "ready"}`(若有前端订阅者,Tag 立即切回"待检测";否则 publish 落 broker 不报错)
