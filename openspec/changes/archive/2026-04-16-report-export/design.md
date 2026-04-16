## Context

M3 9/9 收官后,检测层数据已全部落库(AR + OA + PC + AgentTask),judge 双轨(公式 + L-9 LLM)+ 铁证守护已闭环。M4 首 change 的核心命题是**把这些数据转化为用户可理解、可导出、可复核的闭环**。

四个产品决策(用户已敲定):
- Q1 Word 模板:内置默认 + 用户上传可覆盖 + 上传坏回退内置
- Q2 复核粒度:整报告级最终结论(必)+ 维度级标记(选)
- Q3 操作日志:独立 audit_log 表全字段,写入 try/except 兜底
- Q4 导出异步:async_tasks + SSE 复用 + 三兜底(失败重试 / 模板坏回退 / 7 天过期)

本文档把产品决策落成 ~15 条技术决策(D1~D15),design 阶段自己敲定,用户整组 review。

## Goals / Non-Goals

**Goals:**
- 把 AR/OA/PC/AgentTask 数据完整暴露给前端(4 页 + 复核 + 导出)
- Word 异步导出复用 async_tasks 基础设施,0 新调度机制
- 复核/导出/日志三路径各自兜底,不互相污染
- 检测层零改动(不动 C6~C14 任何代码/测试)

**Non-Goals:**
- 不做用户模板上传完整 UI(预留 endpoint + 校验,上传/管理 UI 作为 follow-up)
- 不做批量导出 / 批量复核
- 不做 PDF 导出(Word 足够,PDF 延后)
- 不改 AnalysisReport / OverallAnalysis / PairComparison 既有字段契约(只加新字段)
- 不引入新的前端全局状态管理库

## Decisions

### D1. Word 生成库选型:docxtpl
**选型**:`docxtpl 0.16+`(基于 python-docx + jinja2)。
**理由**:
- 模板即 .docx 文件,含 `{{ placeholder }}` 和 `{% for %}` 循环,非技术人员可直接在 Word 里编辑
- 与"用户模板上传"决策天然契合:用户上传的是标准 .docx(自带占位符),校验就是 load + render dry-run
- 比 python-docx 纯代码生成更易维护(内置模板样式所见即所得)
**拒绝方案**:`python-docx` 纯代码(样式硬编码难维护);`reportlab`(PDF 导向,非目标)。

### D2. 复核字段加在哪
**选型**:AR 加 4 字段 + OA 加 1 字段(nullable),**不新建 manual_review 表**。
- `AnalysisReport`:`manual_review_status` VARCHAR(16) nullable(枚举值 'confirmed'/'rejected'/'downgraded'/'upgraded',null = 未复核),`manual_review_comment` TEXT nullable,`reviewer_id` FK→User nullable,`reviewed_at` TIMESTAMPTZ nullable
- `OverallAnalysis`:`manual_review_json` JSONB nullable(维度级标记,schema:`{action, comment, reviewer_id, at}`)
**理由**:一个 report 只有一个最终结论,AR 1:1 自然;OA 已是 11 行/report,维度级标记就地存最经济。独立表意味额外 JOIN 且没有多版本需求。
**AR 与 `risk_level` 的关系**:复核字段 `manual_review_status` ≠ `risk_level`(C6 已有,检测原值)。复核**不覆盖** `risk_level`,只加新的 review 字段作并列结论(见 D11)。
**拒绝方案**:独立 `manual_reviews` 表(过度设计,1:1 关系不需要)。

### D3. audit_log 表结构 + action 枚举
**字段**(完整版,Q3 A 方案):
```
id BIGSERIAL PK
project_id BIGINT FK→Project (index)
report_id BIGINT FK→AnalysisReport nullable (index)  -- 某些 project 级动作无 report
actor_id BIGINT FK→User
action VARCHAR(64)  -- 枚举见下
target_type VARCHAR(32)  -- 'report' / 'report_dimension' / 'export' / 'template'
target_id VARCHAR(64) nullable  -- 维度名 / export_task_id / 模板 id
before_json JSONB nullable  -- 复核类动作填;导出类动作空
after_json JSONB nullable
ip VARCHAR(45) nullable  -- IPv4/IPv6
user_agent VARCHAR(255) nullable
created_at TIMESTAMPTZ default now() (index)
```
**action 枚举**(V1):
- `review.report_confirmed` / `review.report_rejected` / `review.report_downgraded` / `review.report_upgraded`
- `review.dimension_marked`(维度级标记)
- `export.requested` / `export.succeeded` / `export.failed` / `export.downloaded` / `export.fallback_to_builtin`
- `template.uploaded`(预留,本 change 不触发)
**索引**:`(project_id, created_at DESC)` + `(report_id, created_at DESC)`。

### D4. 新建 `export_jobs` 独立表(apply 阶段就地改:B2)
**背景**:apply 读代码发现 `AsyncTask` 是轻量心跳追踪(仅 subtype/entity/status/heartbeat/error,无 JSON 字段,4 subtype 枚举闭合)— 扩字段 + 扩枚举侵入面比预期大。改为独立表更干净。
**决策**:新建 `export_jobs` 表,字段:
```
id BIGSERIAL PK
project_id BIGINT FK→projects NOT NULL
report_id BIGINT FK→analysis_reports NOT NULL
actor_id BIGINT FK→users NOT NULL
template_id BIGINT FK→templates NULL
status VARCHAR(16) NOT NULL DEFAULT 'pending'  -- pending|running|succeeded|failed
file_path VARCHAR(512) NULL
file_size BIGINT NULL
fallback_used BOOLEAN NOT NULL DEFAULT false
error TEXT NULL
file_expired BOOLEAN NOT NULL DEFAULT false  -- 7 天清理标记
started_at TIMESTAMPTZ NULL
finished_at TIMESTAMPTZ NULL
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```
索引:`(project_id, created_at DESC)` + `(report_id, created_at DESC)` + `(status, finished_at)`(供清理 worker)。
**SSE**:复用 `progress_broker.publish(project_id, "export_progress", {job_id, phase, progress, message})`;事件类型 `export_progress`(不动现有 `agent_status` / `parse_progress` 类型)。
**worker 调度**:触发 endpoint 创建 export_job row(status=pending)+ `asyncio.create_task(run_export(job_id))`;run_export 置 running → 渲染 → 终态 succeeded/failed。**不接入 AsyncTask 心跳**(导出单次生成通常 < 30 s,不需要心跳恢复;服务器重启未完成 job 由用户手动重试处理)。
**失败语义**:status='failed',error 字段填原因;前端重试 = 新建 job(新 job_id)。
**幂等**:不幂等,允许重复创建 job(由用户主动控制)。

### D5. 文件落盘 + 过期清理
- 路径:`uploads/exports/{job_id}.docx`(job_id 为 export_jobs.id,INT64,与 report_id 不冲突)
- 保留:7 天;过期判定 `NOW - export_jobs.finished_at > 7 days`
- 清理:后台 worker 每日 02:00 扫 `export_jobs WHERE status='succeeded' AND finished_at < NOW - 7days AND file_expired=false` → rm file + UPDATE `file_expired=true`
- 下载 endpoint `GET /api/exports/{job_id}/download`:先查 file_expired=false 且 status='succeeded' → 200 stream;file_expired=true → **410 Gone** body `{"error":"file_expired","hint":"点击重新生成"}`;status != succeeded → 409
**理由**:7 天够审计复查又不长期占磁盘;410 是标准"曾存在已消失"语义,前端可据此提示。

### D6. 内置模板 default.docx 结构
**占位符 schema**(docxtpl jinja2):
```
{{ project.name }} / {{ project.submitted_at }}
{{ report.total_score }} / {{ report.level }} / {{ report.llm_conclusion }}
{% for dim in dimensions %}  ← 11 维度循环
  {{ dim.name }} / {{ dim.score }} / {{ dim.level }} / {{ dim.evidence_summary }}
  {% if dim.has_iron_evidence %}【铁证】{% endif %}
{% endfor %}
{% for pair in top_pairs %}  ← top-k 高风险对(k=design 5)
  {{ pair.bidder_a }} vs {{ pair.bidder_b }} / {{ pair.overall_score }}
{% endfor %}
{% if review %}人工复核:{{ review.status }} / {{ review.comment }}{% endif %}
```
**理由**:字段直接来自 AR/OA/PC 既有列,零 transform;top-k 避免长文档爆量;review 段条件渲染,未复核报告自然省略。

### D7. 用户模板上传:本 change 只预留骨架
**本 change 做**:
- `services/export/templates.py` 支持 `load_template(template_id | None)`,None → 内置,非 None → 从 `template_id` 查 DB + 加载
- 加一个 `templates` 表骨架(`id, owner_id, name, file_path, created_at`),**但不暴露 upload endpoint**(只有 admin 可直接 INSERT,通过 DB 演示)
- docxtpl render 异常统一捕获 → fallback 内置 + audit_log 记 `export.fallback_to_builtin`

**本 change 不做**:
- 用户上传 UI / 管理页
- 模板版本管理
- 占位符校验工具

**follow-up issue 记到 proposal Impact**。

### D8. 前端页面路由组织
```
/projects/:pid/reports/:rid          → Report.tsx(总览 Tab 默认)
/projects/:pid/reports/:rid/dim      → DimensionDetail.tsx(11 维度下钻)
/projects/:pid/reports/:rid/compare  → Compare.tsx(pair 对比入口)
/projects/:pid/reports/:rid/logs     → AuditLog.tsx(检测日志 + 操作日志合并)
```
**ExportButton / ReviewPanel**:作为组件嵌入 Report.tsx 总览页顶部工具条。
**理由**:与 C6 建的 `pages/Report.tsx` 路径一致,沿用即可;4 个子页用 Tab / 二级 Route 都可,选 Route 以便直接粘链接分享。

### D9. 导出 SSE 进度消息格式
基于现有 `progress_broker`(project 级 pub/sub),新增事件类型 `export_progress`,`data` 格式:
```json
{"job_id": 123, "phase": "rendering|writing|done|failed", "progress": 0.45, "message": "渲染维度明细..."}
```
前端 ExportButton 订阅 `/api/projects/{pid}/analysis/events` 既有 SSE 通道,match `event == "export_progress"` + `data.job_id == my_job` → 显示进度条 / 重试按钮(failed 态)。
**理由**:progress_broker 是 project 级广播,既有 SSE 端点一条通道承接多种事件(agent_status / parse_progress / export_progress);前端只需新增一个 listener,不需要新 endpoint。

### D10. 降级 banner 哨兵匹配
前端 Report.tsx 总览 Tab 读 `report.llm_conclusion`,若 `.startswith("AI 综合研判暂不可用")` → 渲染黄色 banner "AI 综合研判暂不可用,以下内容基于规则公式"。C14 已在 judge_llm.fallback_conclusion 固定此前缀,本 change 只 match,不改后端。

### D11. 复核不改检测原始数据
- `AR.total_score` / `AR.level` / `OA.score` 等检测层字段复核时**不修改**,只写新的 `manual_review_*` 字段
- 导出 Word 若有复核 → 渲染"检测得分:85(高风险);人工复核:降级为中风险,理由:…"两行并列
**理由**:保留检测原值便于审计对比;避免人工结论污染算法可解释性数据。

### D12. audit_log 写入失败不影响主业务
- 写入封装 `audit.log_action(...)` 函数,内部 `try: session.add+commit(独立事务) except Exception: logger.error(...)`
- 主业务逻辑(复核 / 导出触发)在 audit 写入**之后**的独立 session 执行,或用独立 audit session
- L1 测试覆盖:audit DB 写失败时,复核/导出请求仍 200

### D13. 导出失败重试
- 前端 `ExportButton` 订阅到 `phase=failed` → 按钮切"重试"态
- 点重试 → 新建 task(新 task_id),旧 task 记录保留在 async_tasks 作为历史
- 连续失败无上限(用户可反复试);服务端限流依赖既有中间件
**拒绝方案**:自动重试(生成失败多为模板问题,盲重试浪费资源)。

### D14. 测试分层策略(遵循 CLAUDE.md 三层)
- **[L1]** pytest 单元:
  - `export/generator.py` 纯函数(render_context 组装)
  - `export/templates.py` 加载/回退
  - `reviews.py` 字段校验 + 状态机
  - `audit.py` log_action 幂等 + 失败吞异常
  - 前端 Vitest:ReviewPanel / ExportButton / AuditLog 组件渲染 + 降级 banner match
- **[L2]** e2e pytest + TestClient:
  - S1 导出全链路:启动 task → SSE progress → 文件生成 → 下载 200
  - S2 用户模板坏:触发 fallback → audit_log 记 fallback_to_builtin → 文件仍下载成功
  - S3 导出失败路径:render 异常 → task FAILED + audit_log export.failed
  - S4 复核整报告:POST review → AR 4 字段更新 + audit_log review.report_confirmed
  - S5 复核维度级:POST dimension review → OA.manual_review_json 更新
  - S6 文件过期:手工设 finished_at=8 天前 → GET download 返 410
- **[L3]** Playwright:延续 C6~C14 flake 降级策略,占位手工凭证(截图存 `e2e/artifacts/c15-2026-04-NN/`)

### D15. Follow-ups(本 change 不做)
记到 proposal Impact 或本文档尾部:
- [ ] 用户模板上传 UI / 校验工具 / 版本管理
- [ ] PDF 导出
- [ ] 批量导出 / 批量复核
- [ ] 审计日志过滤器(按 action / actor / 时间)
- [ ] 导出历史页(列出用户过去 7 天内所有 export task)

## Risks / Trade-offs

- **[docxtpl 渲染异常多样]** → D7 + D12 兜底:统一 try/except,回退内置模板 + audit_log 可溯源
- **[并发导出同一 report 占磁盘]** → D5 保留 7 天 + D4 不幂等(允许重复 task);磁盘压力小(单报告 <1MB × 7 天 × N 用户)
- **[audit_log 高频写入慢]** → D3 索引 + D12 独立事务,写慢不阻塞主业务
- **[复核字段加入 AR 破坏既有 test]** → L1 nullable 新字段 + 默认值,既有 test 零改动验证
- **[7 天过期对审计需求短]** → D15 follow-up 加"导出历史"页 + 可配置保留期(本 change 默认 7 天硬编码)

## Migration Plan

1. alembic migration:`audit_log` 建表 + `AR` 加 4 字段 + `OA` 加 1 字段 + `templates` 表骨架
2. 部署顺序:后端 migration → 后端代码 → 内置模板 default.docx → 前端代码
3. 回滚:migration 可逆(字段都 nullable),旧代码不读新字段即可

## Open Questions

无(4 产品决策已敲定,D1~D15 实施细节已自决)。
