## ADDED Requirements

### Requirement: audit_log 表结构

系统 MUST 建立 `audit_log` 表,字段(PK/FK/index 标注见下):
- `id BIGSERIAL PK`
- `project_id BIGINT NOT NULL FK→projects(id) INDEX`
- `report_id BIGINT NULL FK→analysis_reports(id) INDEX`
- `actor_id BIGINT NOT NULL FK→users(id)`
- `action VARCHAR(64) NOT NULL`(枚举见下条 Requirement)
- `target_type VARCHAR(32) NOT NULL`
- `target_id VARCHAR(64) NULL`
- `before_json JSONB NULL`
- `after_json JSONB NULL`
- `ip VARCHAR(45) NULL`
- `user_agent VARCHAR(255) NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW() INDEX`

复合索引:`(project_id, created_at DESC)` 和 `(report_id, created_at DESC)`。

#### Scenario: migration 建表成功
- **WHEN** 执行 alembic upgrade head
- **THEN** audit_log 表存在且字段/索引与上述一致

#### Scenario: report_id 可空
- **WHEN** 插入一条 project 级动作(如 `template.uploaded`),report_id=NULL
- **THEN** 插入成功(NOT NULL 约束仅针对 project_id 和 actor_id)

---

### Requirement: audit action 枚举(V1)

V1 版本 `audit.log_action(...)` MUST 在应用层校验 action 字段,仅允许以下值:
- 复核类:`review.report_confirmed` / `review.report_rejected` / `review.report_downgraded` / `review.report_upgraded` / `review.dimension_marked`
- 导出类:`export.requested` / `export.succeeded` / `export.failed` / `export.downloaded` / `export.fallback_to_builtin`
- 模板类(预留):`template.uploaded`

非法 action MUST 抛 `ValueError` 且不写入 DB。

#### Scenario: 合法 action 写入
- **WHEN** 复核成功调用 audit.log_action(action='review.report_confirmed', ...)
- **THEN** 记录成功

#### Scenario: 非法 action 抛异常
- **WHEN** 代码传入未列出的 action 如 'foo.bar'
- **THEN** log_action 抛 ValueError;无 audit_log 行写入

---

### Requirement: audit_log 写入失败不影响主业务

`audit.log_action(...)` 函数 MUST:
1. 使用独立事务 session(不与主业务事务共享)
2. `try: session.add + commit except Exception: logger.error(...)` 吞异常
3. 即使 audit 写入失败,主业务请求仍返回原正常响应(复核 200 / 导出 202)

#### Scenario: audit DB 不可用时复核仍成功
- **WHEN** audit_log 表被锁或连接池满,log_action 抛异常
- **THEN** 复核 endpoint 仍返 200;AR 字段已更新;logger 有 error 记录

#### Scenario: audit 写入成功不中断响应
- **WHEN** 正常场景复核成功
- **THEN** audit_log 有 1 行新记录;主响应 200

---

### Requirement: before_json / after_json 填充约定

audit.log_action 调用方 MUST 按以下约定填充 before_json / after_json:
- **复核类动作**:before_json MUST 填复核前 `{status, comment}` 快照;after_json MUST 填复核后快照
- **导出类动作**:before_json 和 after_json 可空(`export.requested` 无前状态);`export.fallback_to_builtin` 例外,before MUST={template_id},after MUST={fallback_template}
- **其他动作**:初期可空,后续按需扩展

#### Scenario: 复核类 before/after 对称
- **WHEN** 记录 `review.report_confirmed`
- **THEN** before_json={status: null, comment: null};after_json={status:'confirmed', comment:'...'}

#### Scenario: 导出请求 before/after 空
- **WHEN** 记录 `export.requested`
- **THEN** before_json 和 after_json 均可为 null(target_id=task_id)

#### Scenario: fallback 动作记录两端模板
- **WHEN** 记录 `export.fallback_to_builtin`
- **THEN** before_json={template_id: 3};after_json={fallback_template: 'default.docx'}

---

### Requirement: 操作日志查询端点

系统 SHALL 提供 `GET /api/projects/{pid}/audit_logs` 端点,返回该 project 下的 audit_log 按 created_at DESC;支持 query:`?report_id=<id>` / `?action=<prefix>` / `?limit=100`(默认)/ `?offset=0`。权限与 report-view 一致。

#### Scenario: 按 project 查询
- **WHEN** GET /audit_logs
- **THEN** 200 + 该 project 所有日志倒序

#### Scenario: 按 report 过滤
- **WHEN** GET /audit_logs?report_id=42
- **THEN** 只返 report_id=42 的日志

#### Scenario: 按 action 前缀过滤
- **WHEN** GET /audit_logs?action=review.
- **THEN** 只返 action 以 'review.' 开头的条目(复核类)
