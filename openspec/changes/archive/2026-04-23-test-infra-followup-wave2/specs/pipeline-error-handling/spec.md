## ADDED Requirements

### Requirement: 测试基础设施鲁棒性契约

为防止"前序 hardening 的契约在基础设施噪声中被静默破坏",本 capability SHALL 锁定以下 3 个稳定测试基础设施契约点(不锁 heuristic / 参数阈值 / 内部实现,只锁可观测行为):

- **alembic migration 不 disable 应用 logger**:`backend/alembic/env.py` 调用 `logging.config.fileConfig(...)` 时 MUST 显式传 `disable_existing_loggers=False`,保证任何 `app.*` logger 在 alembic upgrade head 跑完后仍可用(`.disabled is False`)。防止 L2 session fixture 意外屏蔽应用 logger 导致 caplog 类测试静默失败
- **`run_isolated` 对 `ProcessPoolExecutor` 内部字段变动 graceful degrade**:finally 块访问 `pool._processes` MUST 通过 `getattr(pool, "_processes", {})` + `try/except (AttributeError, TypeError)` 双重守卫;缺失或非预期类型时 fallback 到纯 `shutdown(wait=False, cancel_futures=True)` 路径,不 raise 到调用方。保证 Py 3.14+ stdlib 潜在变动下 `run_isolated` 仍可被调用且不破坏 isolate 语义
- **engine 层 except 顺序契约由 AST 元测试强制**:`engine._execute_agent_task` 的 `except AgentSkippedError` 必须严格位于 `except Exception` 之前,由 L1 AST 元测试(非正则/文本扫描)静态校验 —— 元测试 MUST 用 `ast.AsyncFunctionDef` visitor 遍历 try 块 handler,确定顺序索引,禁止正则去注释类脆弱方案

本 Requirement 不引入新产品行为,不改 schema / API / 前端;只把 3 个**已在 harden-async-infra / agent-skipped-error-guard / llm-classifier-observability 隐含建立**的契约显式化,防未来回归。

#### Scenario: alembic upgrade 不 disable app logger

- **WHEN** L2 session fixture `_testdb_schema` 启动时调 `alembic upgrade head`,触发 `alembic/env.py:27` 的 `fileConfig(config.config_file_name, disable_existing_loggers=False)`
- **THEN** 此前已通过 `logging.getLogger("app.services.parser.content")` 等 API 创建的应用层 logger 在命令返回后 `.disabled is False`;后续 `caplog.at_level(logging.WARNING, logger="app.services.parser.content")` + `logger.warning(...)` 可被 caplog 捕获

#### Scenario: run_isolated 对 pool 内部字段缺失 graceful fallback

- **WHEN** `run_isolated` 的 `ProcessPoolExecutor` 实例 `_processes` 属性缺失、类型变化、或访问 raise AttributeError/TypeError
- **THEN** finally 块 catch 异常 fallback 到 `processes = []`;继续执行 `pool.shutdown(wait=False, cancel_futures=True)` 完成最基本的资源释放;不 raise 到调用方,agent 任务按既有语义返回 result 或标 skipped/timeout

#### Scenario: engine except 顺序由 AST 元测试校验

- **WHEN** 扫 `backend/app/services/detect/engine.py::_execute_agent_task` 函数定义,解析为 `ast.AsyncFunctionDef`,遍历其 `body` 内所有 `ast.Try` 节点
- **THEN** 若某 try 块的 `handlers` 含 `ast.ExceptHandler(type=ast.Name(id="Exception"))`(通用兜底),则**必须**存在一个位置索引严格小于该 handler 的 `ast.ExceptHandler(type=ast.Name(id="AgentSkippedError"))`;顺序颠倒或缺失 SHALL 令元测试失败,定位到具体文件行号
