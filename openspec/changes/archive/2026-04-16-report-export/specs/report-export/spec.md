## ADDED Requirements

### Requirement: export_jobs 表结构

系统 MUST 建立 `export_jobs` 表,字段:
- `id BIGSERIAL PK`
- `project_id BIGINT FK→projects NOT NULL`
- `report_id BIGINT FK→analysis_reports NOT NULL`
- `actor_id BIGINT FK→users NOT NULL`
- `template_id BIGINT FK→templates NULL`
- `status VARCHAR(16) NOT NULL DEFAULT 'pending'`(枚举 pending/running/succeeded/failed)
- `file_path VARCHAR(512) NULL`
- `file_size BIGINT NULL`
- `fallback_used BOOLEAN NOT NULL DEFAULT false`
- `error TEXT NULL`
- `file_expired BOOLEAN NOT NULL DEFAULT false`
- `started_at TIMESTAMPTZ NULL`
- `finished_at TIMESTAMPTZ NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`

复合索引:`(project_id, created_at DESC)` + `(report_id, created_at DESC)` + `(status, finished_at)`(供清理 worker 高效扫描)。

#### Scenario: migration 建表成功
- **WHEN** 执行 alembic upgrade head
- **THEN** export_jobs 表存在,字段和索引与上述一致

---

### Requirement: 触发异步 Word 导出

系统 SHALL 提供 `POST /api/projects/{project_id}/reports/{version}/export` 端点,body 可选 `{template_id?: int}`。成功:
1. 校验 report 存在 + 权限(reviewer 自己 / admin 任意,否则 404)
2. INSERT export_jobs row(status='pending', project_id/report_id/actor_id/template_id 填入)
3. `asyncio.create_task(run_export(job.id))` 异步调度
4. 响应 **202** + `{"job_id": int}`
5. audit_log 记 `export.requested`(target_type='export', target_id=job.id)

#### Scenario: 触发默认模板导出
- **WHEN** owner POST export(不带 template_id)
- **THEN** 202 + job_id;export_jobs 行 status='pending';audit_log 记 `export.requested`

#### Scenario: 触发用户模板导出(预留)
- **WHEN** owner POST export `{template_id: 3}`
- **THEN** 202 + job_id;export_jobs.template_id=3;后续 worker 加载指定模板

#### Scenario: 他人项目导出返回 404
- **WHEN** reviewer A 对 B 的项目触发导出
- **THEN** 404,不创建 job,不写 audit_log

---

### Requirement: 异步导出 worker 生成 Word 文件

`run_export(job_id)` worker MUST 执行:
1. UPDATE export_jobs SET status='running', started_at=NOW()
2. 通过 progress_broker 发 `export_progress` 事件 `phase=rendering`
3. 加载 report 数据(AR + OA 11 行 + top-k PairComparison,k=5)+ 人工复核字段(若有)
4. 加载模板(template_id 指定 → DB 查路径;否则内置 `default.docx`)
5. 使用 docxtpl 渲染
6. 发 `export_progress` `phase=writing` → 写入 `uploads/exports/{job_id}.docx`
7. UPDATE export_jobs SET status='succeeded', finished_at=NOW(), file_path, file_size
8. 发 `export_progress` `phase=done`
9. 记 audit_log `export.succeeded`

#### Scenario: 默认模板渲染成功
- **WHEN** job 执行且 template_id=null
- **THEN** 使用内置 default.docx;文件落盘;export_jobs.status='succeeded';audit_log 记 `export.succeeded`;SSE 发 `phase=done`

#### Scenario: 进度 SSE 推送
- **WHEN** worker 渲染中
- **THEN** 至少推送 `phase=rendering` → `phase=writing` → `phase=done` 三阶段事件;每事件含 `job_id` 和 `progress` ∈ [0, 1]

---

### Requirement: 用户模板坏自动回退内置

当 template_id 指定的模板加载/渲染任一步异常,worker MUST:
1. 捕获异常
2. 回退内置 default.docx 重新渲染
3. UPDATE export_jobs SET fallback_used=true(status 仍 succeeded)
4. audit_log 记 `export.fallback_to_builtin`(before={template_id},after={fallback_template: "default.docx"})

用户仍得到可下载文件,**不返失败**。

#### Scenario: 用户模板 .docx 损坏
- **WHEN** template_id 指向损坏文件,docxtpl load 抛异常
- **THEN** worker 捕获 → 用 default.docx 重试 → export_jobs.status='succeeded' + fallback_used=true;audit_log 记 `export.fallback_to_builtin`

#### Scenario: 用户模板占位符引用不存在字段
- **WHEN** 模板含 `{{ missing_field }}` 导致 render 异常
- **THEN** 同上回退

---

### Requirement: 导出失败 job FAILED

若内置模板渲染本身失败(罕见,通常为数据不完整)或磁盘写入失败,worker MUST:
1. UPDATE export_jobs SET status='failed', finished_at=NOW(), error=<人可读原因>
2. audit_log 记 `export.failed`
3. SSE 发 `export_progress` `phase=failed`

前端据此显示"重试"按钮。**不自动重试**。

#### Scenario: 内置模板渲染失败
- **WHEN** default.docx 渲染异常(如 AR 数据不完整)
- **THEN** export_jobs.status='failed';audit_log `export.failed`;SSE `phase=failed`

#### Scenario: 前端手动重试
- **WHEN** 用户点击"重试"按钮 → POST 同 report 的 export
- **THEN** 新建 job(新 job_id);旧 job 保留;audit_log 记新的 `export.requested`

---

### Requirement: 下载导出文件

系统 SHALL 提供 `GET /api/exports/{job_id}/download` 端点。job MUST status='succeeded' 且 file_expired=false 才能下载。成功:200 + 二进制流 + header `Content-Disposition: attachment; filename="report_{project_id}_v{version}_{date}.docx"`。记 audit_log `export.downloaded`。

#### Scenario: 下载有效文件
- **WHEN** job status='succeeded' 且 file_expired=false
- **THEN** 200 + docx 二进制流;audit_log 记 `export.downloaded`(含 ip/user_agent)

#### Scenario: 文件过期 410
- **WHEN** job.file_expired=true
- **THEN** 410 Gone,body `{"error":"file_expired","hint":"点击重新生成"}`

#### Scenario: job 未 succeeded
- **WHEN** job.status ∈ {'pending','running','failed'}
- **THEN** 409,body 提示 job 状态

#### Scenario: 无权限下载
- **WHEN** reviewer A 下载 B 的 export job
- **THEN** 404

---

### Requirement: 导出文件 7 天过期清理

系统 MUST 运行后台清理作业:每日 02:00 扫描 `export_jobs WHERE status='succeeded' AND finished_at < NOW - INTERVAL '7 days' AND file_expired=false` → 删除对应磁盘文件 → UPDATE SET `file_expired=true`。单个 job 清理失败 MUST 不中断其他 job 处理(catch 异常 + log + 继续)。

#### Scenario: 正常过期清理
- **WHEN** 清理 worker 运行且有 3 个文件 >7 天 succeeded
- **THEN** 3 个文件被 rm;3 个 job.file_expired=true

#### Scenario: 文件已被人工删除
- **WHEN** 磁盘文件先被人工删除,DB 还未标记
- **THEN** rm 抛 FileNotFoundError → 捕获 → 仍 UPDATE file_expired=true

---

### Requirement: 内置 Word 模板内容契约

`backend/app/services/export/templates/default.docx` MUST 包含如下 docxtpl 占位符段,渲染上下文 schema:
- `project.{name, submitted_at}`
- `report.{version, total_score, risk_level, llm_conclusion}`
- `dimensions[]` 循环,每元素 `{name, best_score, is_ironclad, evidence_summary}`
- `top_pairs[]` 循环(top-k=5),每元素 `{bidder_a, bidder_b, score, is_ironclad, summary}`
- `review` 条件段,`{status, comment, reviewer, reviewed_at}`(无复核时省略整段)

#### Scenario: 最小数据渲染
- **WHEN** 2 bidder 项目完成检测无复核 → 导出
- **THEN** 模板渲染成功;dimensions 11 行;top_pairs 1 行;review 段不出现

#### Scenario: 含复核数据渲染
- **WHEN** 已复核的报告导出
- **THEN** review 段渲染为"人工复核:已确认 / 评论:…"
