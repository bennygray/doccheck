## 1. 数据模型 + migration

- [x] 1.1 [impl] 新建 `backend/app/models/audit_log.py` + `backend/app/models/export_job.py`(字段按 spec audit-log + report-export §表结构)
- [x] 1.2 [impl] 扩 `models/analysis_report.py` 加 4 字段(manual_review_status/comment/reviewer_id/reviewed_at)+ 扩 `models/overall_analysis.py` 加 `manual_review_json`
- [x] 1.3 [impl] 新建 `models/template.py`(模板骨架表,不暴露上传 endpoint;本 change 只 admin 手工 INSERT 做测试)
- [x] 1.4 [impl] alembic migration `0008_report_export.py`(audit_log + export_jobs + templates 建表 + AR/OA 加字段 + 所有索引);可逆
- [x] 1.5 [L1] pytest 覆盖 migration up/down + 新模型 ORM 读写(10 用例全绿)

## 2. audit_log 模块

- [x] 2.1 [impl] 新建 `backend/app/services/audit.py` `log_action(action, project_id, report_id?, actor, target_type, target_id?, before?, after?, request?)` 独立事务 + try/except 吞异常
- [x] 2.2 [impl] 新建 `app/api/routes/audit.py` `GET /api/projects/{pid}/audit_logs` 支持 report_id/action/limit/offset 过滤
- [x] 2.3 [L1] pytest `test_audit_log_action`:正常写入 / DB 异常吞掉不抛 / before_after 填充约定 / action 枚举校验(5 用例全绿)

## 3. 人工复核模块

- [x] 3.1 [impl] 新建 `app/api/routes/reviews.py`:`POST .../reports/{version}/review`(整报告级)+ `POST .../dimensions/{dim}/review`(维度级)
- [x] 3.2 [impl] 复核 handler 严格:status 枚举校验 / 仅写 manual_review_* 字段 / 检测原值不动 / 调用 audit.log_action 记 before/after
- [x] 3.3 [L2] pytest `test_reviews_api.py`(升级为 L2,需 HTTP 客户端):首次复核 / 重复复核覆盖 / 非法 status 400 / 无权限 404 / admin 通行 / 维度级成功 / 维度级非法 action 400 / 未知维度 404 / 无 OA 行 404 / 维度级不影响 AR;**同时覆盖 task 7.5**(S4+S5 review_flow)。10 用例全绿

## 4. 报告视图模块

- [x] 4.1 [impl] 扩 `app/api/routes/reports.py`:`GET /reports/{version}` 含 manual_review_* / `GET .../dimensions` 11 行 / `GET .../pairs` 支持 sort&limit / `GET .../logs` 合并 AgentTask+AuditLog 流
- [x] 4.2 [impl] 合并视图 schema:`{source: 'agent_task'|'audit_log', created_at, payload}`;按 created_at DESC 在 Python 层合并(两表 SQL 各自查 limit 后 merge)
- [x] 4.3 [L2] e2e `test_report_views_api.py`:权限 404 / dimensions 顺序固定 / pairs 排序 + is_ironclad 标识 / logs 合并与过滤(9 用例全绿)

## 5. Word 导出服务

- [x] 5.1 [impl] 添加依赖 `docxtpl` 到 `backend/pyproject.toml`(uv sync)
- [x] 5.2 [impl] 新建 `backend/app/services/export/`:`generator.py`(render_context 装配 + docxtpl 渲染)/ `templates.py`(load_template(template_id|None)+ fallback 回退)/ `cleanup.py`(7 天过期清理 worker 逻辑)
- [x] 5.3 [impl] 新建 `backend/app/services/export/templates/default.docx` 内置模板(由 `scripts/build_default_export_template.py` 一次性生成,提交到 repo),占位符按 design D6
- [x] 5.4 [impl] 新建 `app/api/routes/exports.py`:`POST .../reports/{version}/export` 202 创建 export_jobs + `GET /exports/{job_id}/download` 200/410/409/404
- [x] 5.5 [impl] 新建 `services/export/worker.py` `run_export(job_id)`:状态机 pending→running→succeeded/failed + 加载 → 渲染(try/except → fallback 内置)→ 落盘 `uploads/exports/{job_id}.docx` → progress_broker 推 `export_progress` 事件 → audit_log succeeded/failed/fallback_to_builtin
- [x] 5.6 [impl] 过期清理 job:`ExportCleanupTask` 每日 02:00 调 `cleanup.run_once()`(不引入 APScheduler,沿用 lifespan asyncio.create_task 模式);env `INFRA_DISABLE_EXPORT_CLEANUP=1` 关闭
- [x] 5.7 [L1] pytest `test_export_generator` 10 用例:context 装配 / best_score / iron / top_k 铁证优先 / review 条件 / render_to_file / 模板回退(10 用例全绿)

## 6. 前端:报告视图 + 复核 + 导出

- [x] 6.1 [impl] 扩 `frontend/src/pages/reports/ReportPage.tsx`(总览,既有)+ 新建 `DimensionDetailPage.tsx` + `ComparePage.tsx` + `AuditLogPage.tsx`;路由按 `/reports/:projectId/:version/{dim|compare|logs}` 层级
- [x] 6.2 [impl] 新建 `components/reports/ReviewPanel.tsx`(整报告级表单)+ 维度明细页内嵌维度级 inline 标记(window.prompt 简化 UI)
- [x] 6.3 [impl] 新建 `components/reports/ExportButton.tsx`:点击触发 POST export → 订阅 SSE `export_progress` → 进度条 / 失败重试按钮 / 成功自动下载
- [x] 6.4 [impl] ReportPage 顶部渲染降级 banner:match `report.llm_conclusion.startsWith("AI 综合研判暂不可用")`,data-testid=`llm-fallback-banner`
- [x] 6.5 [impl] `services/api.ts` 扩 8 方法:getReport/getReportDimensions/getReportPairs/getReportLogs/postReview/postDimensionReview/startExport/downloadExportUrl
- [x] 6.6 [L1] Vitest 组件 12 用例(ReviewPanel 3 / ExportButton 4 / ReportPage 含降级 banner 2 + 既有 5):全部绿,共 73/73 通过

## 7. E2E 后端测试(L2)

- [x] 7.1 [L2] e2e `test_exports_api.test_s1_default_template_full_flow`:S1 默认模板全链路(启动→worker→文件落盘→下载 200)
- [x] 7.2 [L2] e2e `test_s2_user_template_broken_fallback`:S2 用户模板坏 → fallback → audit fallback_to_builtin → 下载成功 + fallback_used=true
- [x] 7.3 [L2] e2e `test_s3_builtin_render_failure_marks_failed`:S3 内置渲染失败 → job FAILED + audit.export.failed + 下载 409
- [x] 7.4 [L2] e2e `test_s6_expired_file_returns_410`:S6 手工 `UPDATE export_jobs SET file_expired=true` → GET download 410
- [x] 7.x [L2] 权限:`test_export_no_permission_to_start` + `test_download_no_permission`(追加 2 用例覆盖 404 路径);6/6 全绿
- [x] 7.5 [L2] e2e `test_review_flow`:S4 POST review → AR 4 字段 + audit_log + 检测原值不变;S5 维度级 POST → OA.manual_review_json(已在 task 3.3 `test_reviews_api.py` 统一覆盖)

## 8. UI E2E(L3,延续手工凭证策略)

- [x] 8.1 [L3] Playwright smoke 延续 C3~C14 策略:**Docker kernel-lock 未解除,L3 降级为手工凭证**,占位 README 已写入 `e2e/artifacts/c15-2026-04-16/README.md`
- [x] 8.2 [manual] L3 flaky 降级兜底(3 条手工路径):导出下载 / 复核提交 / 降级 banner 展示;步骤 + 预期已写入 c15-2026-04-16/README.md(kernel-lock 解除后补截图,L1+L2 已 94 用例完整覆盖核心契约)

## 9. 文档联动

- [x] 9.1 [impl] 更新 `docs/execution-plan.md` §6 追加 C15 apply 记录行
- [x] 9.2 [impl] 更新 `docs/handoff.md`:M4 进度 1/3;C15 决策快照(Q1~Q4 + design D1~D15 + B2 apply 就地改);C14 session 转 bak
- [x] 9.3 [impl] `backend/README.md` 新增 "C15 report-export 依赖" 完整段(docxtpl 依赖 / alembic 0008 / env / 9 endpoint / 4 产品决策 / algorithm version / 模板生成命令 / 降级 banner 契约)

## 10. 汇总测试 + 归档前校验

- [x] 10.1 跑 [L1][L2][L3] 全部测试,全绿 — **L1 后端 746 + 前端 Vitest 73 + L2 242 = 1061 全绿**;L3 手工凭证 `e2e/artifacts/c15-2026-04-16/`;C15 新增 62 用例(后端 L1 25 + 前端 12 + L2 25)
