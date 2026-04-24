## MODIFIED Requirements

### Requirement: AgentSkippedError 异常契约

`app/services/detect/errors.py` SHALL 定义 `class AgentSkippedError(Exception)`,`__init__(self, reason: str)` 参数 reason 作为中文降级文案(已包含"已跳过"结尾)。Agent 层在遇到"应跳过"的运行期异常时 SHALL raise 此异常;`engine._execute_agent_task` SHALL 在通用 `Exception` 捕获之前专门捕获 `AgentSkippedError` 并走 `_mark_skipped(session, task, str(exc))` 路径。

**同时**:所有 agent 的 `run()` 函数内部若存在 `except Exception` 通用兜底(无论当前是否抛 AgentSkippedError),SHALL 在其**之前**前置 `except AgentSkippedError: raise`,防止 agent 未来引入 AgentSkippedError 抛出路径时,异常被通用 except 静默吞为 failed。该约束由元测试(静态扫 `agents/*.py` AST)强制。

#### Scenario: 异常被 engine 路由为 skipped
- **WHEN** 任意 agent 在 `run()` 中 raise `AgentSkippedError("LLM 超时,已跳过")`
- **THEN** engine 捕获该异常 → AgentTask `status=skipped`、`summary` 为 "LLM 超时,已跳过";不走 `_mark_failed`(status=failed) 路径

#### Scenario: 其他异常保持 failed 语义
- **WHEN** agent 在 `run()` 中 raise 非 `AgentSkippedError` 的异常(如 KeyError / ValueError)
- **THEN** engine 走既有 `_mark_failed` 路径,`status=failed`,保持与本 change 前行为一致

#### Scenario: agent 内 except 顺序防御(元测试强制)
- **WHEN** 扫 `backend/app/services/detect/agents/` 下所有 agent 入口文件的 async `run()` 函数
- **THEN** 若该函数内部的 try 块有 `except Exception` 分支,则**必须**存在一个位置严格在其之前的 `except AgentSkippedError` 分支(允许空体 `raise`,或带 OA stub 写入后 `raise`);元测试检测到缺失或顺序颠倒 SHALL 失败,防止未来新 agent 忘加或重构破坏 H2 契约
