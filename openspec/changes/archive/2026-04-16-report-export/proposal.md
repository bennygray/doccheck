## Why

M3 检测层已 9/9 收官(C6~C14),11 Agent + judge 双轨(公式+LLM)+ 铁证守护链路已闭环,数据层(AnalysisReport / OverallAnalysis / PairComparison / AgentTask)填齐但**尚未对最终用户可见**。M4 首个 change 需把"沉在 DB 里的检测结果放出来":报告总览、维度明细、pair 对比入口、检测日志、人工复核、Word 导出 — 覆盖 US-6.1~6.6,形成"上传→检测→报告→导出→复核"完整业务闭环。

## What Changes

### 报告展示层(US-6.1~6.4)
- 新增前端 4 个页面/Tab:报告总览、11 维度明细、pair 对比入口、检测日志(合并 AgentTask 执行日志 + 新 audit_log 操作日志)
- 后端 `reports` 路由扩展:只读 endpoint 暴露 AR+OA+PC+AgentTask 聚合视图,检测层零改动
- 前端降级 banner:match `judge.llm_conclusion` 前缀哨兵 `"AI 综合研判暂不可用"`(C14 定)

### Word 异步导出(US-6.6)
- 新增 `exports` 路由 + `services/export/` 模块:docx 生成 + 模板管理
- **内置模板**:`backend/app/services/export/templates/default.docx`(docxtpl 占位符)
- **用户模板上传**:预留接口 + 校验,完整上传/管理 UI 作为 follow-up
- **异步执行**:复用 async_tasks + SSE(type='export'),task_id → 文件落盘 `uploads/exports/{task_id}.docx` → 下载 endpoint 返二进制
- **三兜底**:① 生成失败 → task FAILED,前端重试按钮;② 用户模板解析坏 → 自动回退内置 + audit_log 记 fallback_to_builtin;③ 文件保留 7 天,过期返 410 + "点击重新生成"

### 人工复核(US-6.5)
- 新增 `reviews` 路由
- **AnalysisReport** 扩 4 字段:`manual_review_status` / `manual_review_comment` / `reviewer_id` / `reviewed_at`(整报告级最终结论,必填路径)
- **OverallAnalysis** 扩 1 字段:`manual_review_json`(nullable,维度级标记,可跳过)
- 复核动作不修改检测原始数据(不动 score/level),只在新字段写最终人工结论

### 操作日志(cross-cutting)
- 新增 `audit_log` 表(独立,不复用 async_tasks / AgentTask):`id, project_id, report_id, actor_id, action, target_type, target_id, before_json, after_json, ip, user_agent, created_at`
- 前端 `AuditLog.tsx` 页展示
- 写入放事务外 try/except,失败不影响主业务
- before/after_json 初期只对"复核"动作填,导出/下载等动作可空

## Capabilities

### New Capabilities
- `report-view`: 报告展示视图层 — 总览 / 维度明细 / pair 对比入口 / 检测+操作日志合并视图(US-6.1~6.4)
- `report-export`: Word 报告异步导出 — 内置模板 + 用户模板预留 + 三兜底(US-6.6)
- `manual-review`: 人工复核 — 整报告级最终结论(必)+ 维度级标记(选)(US-6.5)
- `audit-log`: 操作日志 — 独立 audit_log 表全字段,审计追溯(cross-cutting)

### Modified Capabilities
<!-- 无 — 不修改 detect-framework / parser-pipeline 等既有 spec 的 requirements;AR/OA 加字段属实现细节,对外契约(既有字段)不变 -->

## Impact

### 新增代码
- 后端:`app/api/routes/exports.py` / `audit.py` / `reviews.py`(新);`reports.py`(扩)
- 后端:`services/export/`(docx 生成 / 内置模板加载 / 用户模板 parse + 回退 / 过期清理)
- 后端:`models/audit_log.py`;扩 `models/analysis_report.py` + `models/overall_analysis.py` 各加字段
- 后端:alembic migration(audit_log 建表 + AR/OA 加字段)
- 前端:`pages/Report.tsx`(总览)/ `DimensionDetail.tsx` / `Compare.tsx` / `AuditLog.tsx`;`components/ReviewPanel.tsx` / `ExportButton.tsx`
- 资产:`backend/app/services/export/templates/default.docx`

### 复用(不改)
- `async_tasks` 表 + SSE 调度(M2 C5)— 只新增 task type='export'
- `llm_mock.py` — 本 change 不涉及 LLM
- 前端 SSE hook(M2 既有)

### 不动
- C6~C14 全部检测层代码(detect-framework spec)
- AnalysisReport / OverallAnalysis / PairComparison / AgentTask 既有字段契约
- judge 纯函数 + judge_llm L-9 路径
- parser-pipeline / file-upload / auth / project-mgmt specs

### 依赖 / 风险
- 新 Python 依赖:`docxtpl`(或 `python-docx-template`)— 本 change design 阶段选型
- 兜底覆盖 3 类失败路径(生成失败 / 模板坏 / 文件过期),flake 风险低
- L3 UI 测试延续 C6~C14 手工凭证降级策略
